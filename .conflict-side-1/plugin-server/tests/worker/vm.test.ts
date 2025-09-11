import { mockProducerObserver } from '../helpers/mocks/producer.mock'

// eslint-disable-next-line no-restricted-imports
import { fetch } from 'undici'

import { PluginEvent, ProcessedPluginEvent } from '@posthog/plugin-scaffold'

import { KAFKA_PLUGIN_LOG_ENTRIES } from '../../src/config/kafka-topics'
import { Hub, PluginLogEntrySource, PluginLogEntryType } from '../../src/types'
import { PluginConfig, PluginConfigVMResponse } from '../../src/types'
import { closeHub, createHub } from '../../src/utils/db/hub'
import { UUIDT, delay } from '../../src/utils/utils'
import { createPluginConfigVM } from '../../src/worker/vm/vm'
import { pluginConfig39 } from '../helpers/plugins'
import { plugin60 } from '../helpers/plugins'
import { resetTestDatabase } from '../helpers/sql'

jest.mock('../../src/utils/logger')

jest.setTimeout(100000)

const defaultEvent = {
    uuid: new UUIDT().toString(),
    distinct_id: 'my_id',
    ip: '127.0.0.1',
    site_url: 'http://localhost',
    team_id: 3,
    now: new Date().toISOString(),
    timestamp: new Date().toISOString(),
    event: 'default event',
    properties: {},
}

// since we introduced super lazy vms, setupPlugin does not run immediately with
// createPluginConfigVM - this function sets up the VM and runs setupPlugin immediately after
export const createReadyPluginConfigVm = async (
    hub: Hub,
    pluginConfig: PluginConfig,
    indexJs: string
): Promise<PluginConfigVMResponse> => {
    const vmResponse = createPluginConfigVM(hub, pluginConfig, indexJs)
    await vmResponse.vm.run(`${vmResponse.vmResponseVariable}.methods.setupPlugin?.()`)
    return vmResponse
}
describe('vm tests', () => {
    let hub: Hub

    beforeEach(async () => {
        hub = await createHub()

        jest.mocked(fetch).mockImplementation((...args) => {
            const responsesToUrls: Record<string, any> = {
                'https://google.com/results.json?query=fetched': { count: 2, query: 'bla', results: [true, true] },
                'https://app.posthog.com/api/event?token=THIS+IS+NOT+A+TOKEN+FOR+TEAM+2': { hello: 'world' },
                'https://onevent.com/': { success: true },
                'https://www.example.com': { example: 'data' },
            }

            const response = responsesToUrls[args[0] as unknown as string] || { fetch: 'mock' }

            return Promise.resolve({
                json: jest.fn().mockResolvedValue(response),
            } as any)
        })
    })

    afterEach(async () => {
        await closeHub(hub)
        jest.mocked(fetch).mockClear()
    })

    test('empty plugins', async () => {
        const indexJs = ''
        const vm = await createReadyPluginConfigVm(hub, pluginConfig39, indexJs)

        expect(Object.keys(vm).sort()).toEqual(['methods', 'usedImports', 'vm', 'vmResponseVariable'])
        expect(Object.keys(vm.methods).sort()).toEqual([
            'composeWebhook',
            'getSettings',
            'onEvent',
            'processEvent',
            'setupPlugin',
            'teardownPlugin',
        ])
        expect(vm.methods.processEvent).toEqual(undefined)
    })

    test('setupPlugin sync', async () => {
        const indexJs = `
            function setupPlugin (meta) {
                meta.global.data = 'haha'
            }
            function processEvent (event, meta) {
                event.event = meta.global.data
                return event
            }
        `
        await resetTestDatabase(indexJs)
        const vm = await createReadyPluginConfigVm(hub, pluginConfig39, indexJs)
        const newEvent = await vm.methods.processEvent!({ ...defaultEvent })
        expect(newEvent.event).toEqual('haha')
    })

    test('setupPlugin async', async () => {
        const indexJs = `
            async function setupPlugin (meta) {
                await new Promise(resolve => __jestSetTimeout(resolve, 500))
                meta.global.data = 'haha'
            }
            function processEvent (event, meta) {
                event.event = meta.global.data
                return event
            }
        `
        await resetTestDatabase(indexJs)
        const vm = await createReadyPluginConfigVm(hub, pluginConfig39, indexJs)
        const newEvent = await vm.methods.processEvent!({ ...defaultEvent })
        expect(newEvent.event).toEqual('haha')
    })

    test('teardownPlugin', async () => {
        const indexJs = `
            function setupPlugin (meta) {
                meta.global.data = 'haha'
            }
            function teardownPlugin (meta) {
                fetch('https://google.com/results.json?query=' + meta.global.data)
            }
            function processEvent (event, meta) {
                meta.global.data = event.properties.haha
                return event
            }
        `
        await resetTestDatabase(indexJs)
        const vm = await createReadyPluginConfigVm(hub, pluginConfig39, indexJs)
        await vm.methods.processEvent!({
            ...defaultEvent,
            properties: { haha: 'hoho' },
        })
        expect(fetch).not.toHaveBeenCalled()
        await vm.methods.teardownPlugin!()
        expect(fetch).toHaveBeenCalledWith('https://google.com/results.json?query=hoho', expect.anything())
    })

    test('processEvent', async () => {
        const indexJs = `
            function processEvent (event, meta) {
                event.event = 'changed event'
                return event
            }
        `
        await resetTestDatabase(indexJs)
        const vm = await createReadyPluginConfigVm(hub, pluginConfig39, indexJs)
        expect(vm.methods.processEvent).not.toEqual(undefined)

        const event: PluginEvent = {
            ...defaultEvent,
            event: 'original event',
        }
        const newEvent = await vm.methods.processEvent!(event)
        expect(event.event).toEqual('changed event')
        expect(newEvent.event).toEqual('changed event')
        expect(newEvent).toBe(event)
    })

    test('async processEvent', async () => {
        const indexJs = `
            async function processEvent (event, meta) {
                event.event = 'changed event'
                return event
            }
        `
        await resetTestDatabase(indexJs)
        const vm = await createReadyPluginConfigVm(hub, pluginConfig39, indexJs)
        expect(vm.methods.processEvent).not.toEqual(undefined)

        const event: PluginEvent = {
            ...defaultEvent,
            event: 'original event',
        }
        const newEvent = await vm.methods.processEvent!(event)
        expect(event.event).toEqual('changed event')
        expect(newEvent.event).toEqual('changed event')
        expect(newEvent).toBe(event)
    })

    // this is deprecated, but still works
    test('processEventBatch', async () => {
        const indexJs = `
            function processEventBatch (events, meta) {
                return events.map(event => {
                    event.event = 'changed event'
                    return event
                })
            }
        `
        await resetTestDatabase(indexJs)
        const vm = await createReadyPluginConfigVm(hub, pluginConfig39, indexJs)
        expect(vm.methods.processEvent).not.toEqual(undefined)

        const event: PluginEvent = {
            ...defaultEvent,
            event: 'original event',
        }
        const newEvent = await vm.methods.processEvent!(event)
        expect(event.event).toEqual('changed event')
        expect(newEvent.event).toEqual('changed event')
        expect(newEvent).toBe(event)
    })

    test('async processEventBatch', async () => {
        const indexJs = `
            async function processEventBatch (events, meta) {
                return events.map(event => {
                    event.event = 'changed event'
                    return event
                })
            }
        `
        await resetTestDatabase(indexJs)
        const vm = await createReadyPluginConfigVm(hub, pluginConfig39, indexJs)
        expect(vm.methods.processEvent).not.toEqual(undefined)

        const event: PluginEvent = {
            ...defaultEvent,
            event: 'original event',
        }
        const newEvent = await vm.methods.processEvent!(event)
        expect(event.event).toEqual('changed event')
        expect(newEvent.event).toEqual('changed event')
        expect(newEvent).toBe(event)
    })

    test('processEvent && processEventBatch', async () => {
        const indexJs = `
            function processEvent (event, meta) {
                event.event = 'changed event 1'
                return event
            }
            function processEventBatch (events, meta) {
                return events.map(event => {
                    event.event = 'changed event 2'
                    return event
                })
            }
        `
        await resetTestDatabase(indexJs)
        const vm = await createReadyPluginConfigVm(hub, pluginConfig39, indexJs)
        expect(vm.methods.processEvent).not.toEqual(undefined)

        const event: PluginEvent = {
            ...defaultEvent,
            event: 'original event',
        }
        const newEvent = await vm.methods.processEvent!(event)
        expect(event.event).toEqual('changed event 1')
        expect(newEvent.event).toEqual('changed event 1')
        expect(newEvent).toBe(event)
    })

    test('processEvent without returning', async () => {
        const indexJs = `
            function processEvent (event, meta) {
                event.event = 'changed event'
            }
        `
        await resetTestDatabase(indexJs)
        const vm = await createReadyPluginConfigVm(hub, pluginConfig39, indexJs)
        expect(vm.methods.processEvent).not.toEqual(undefined)

        const event: PluginEvent = {
            ...defaultEvent,
            event: 'original event',
        }

        const newEvent = await vm.methods.processEvent!(event)
        // this will be changed
        expect(event.event).toEqual('changed event')
        // but nothing was returned --> bail
        expect(newEvent).toEqual(undefined)
    })

    test('async processEvent', async () => {
        const indexJs = `
            async function processEvent (event, meta) {
                await new Promise((resolve) => resolve())
                event.event = 'changed event'
                await new Promise((resolve) => resolve())
                return event
            }
        `
        await resetTestDatabase(indexJs)
        const vm = await createReadyPluginConfigVm(hub, pluginConfig39, indexJs)

        const event: PluginEvent = {
            ...defaultEvent,
            event: 'original event',
        }
        await vm.methods.processEvent!(event)

        expect(event.event).toEqual('changed event')
    })

    describe('vm exports', () => {
        test('module.exports override', async () => {
            const indexJs = `
                function myProcessEventFunction (event, meta) {
                    event.event = 'changed event';
                    return event
                }
                module.exports = { processEvent: myProcessEventFunction }
            `
            await resetTestDatabase(indexJs)
            const vm = await createReadyPluginConfigVm(hub, pluginConfig39, indexJs)

            const event: PluginEvent = {
                ...defaultEvent,
                event: 'original event',
            }
            await vm.methods.processEvent!(event)

            expect(event.event).toEqual('changed event')
        })

        test('module.exports set', async () => {
            const indexJs = `
                function myProcessEventFunction (event, meta) {
                    event.event = 'changed event';
                    return event
                }
                module.exports.processEvent = myProcessEventFunction
            `
            await resetTestDatabase(indexJs)
            const vm = await createReadyPluginConfigVm(hub, pluginConfig39, indexJs)

            const event: PluginEvent = {
                ...defaultEvent,
                event: 'original event',
            }
            await vm.methods.processEvent!(event)

            expect(event.event).toEqual('changed event')
        })

        test('exports override', async () => {
            const indexJs = `
                function myProcessEventFunction (event, meta) {
                    event.event = 'changed event';
                    return event
                }
                exports = { processEvent: myProcessEventFunction }
            `
            await resetTestDatabase(indexJs)
            const vm = await createReadyPluginConfigVm(hub, pluginConfig39, indexJs)
            const event: PluginEvent = {
                ...defaultEvent,
                event: 'original event',
            }
            await vm.methods.processEvent!(event)

            expect(event.event).toEqual('changed event')
        })

        test('exports set', async () => {
            const indexJs = `
                function myProcessEventFunction (event, meta) {
                    event.event = 'changed event';
                    return event
                }
                exports.processEvent = myProcessEventFunction
            `
            await resetTestDatabase(indexJs)
            const vm = await createReadyPluginConfigVm(hub, pluginConfig39, indexJs)
            const event: PluginEvent = {
                ...defaultEvent,
                event: 'original event',
            }
            await vm.methods.processEvent!(event)

            expect(event.event).toEqual('changed event')
        })

        test('export', async () => {
            const indexJs = `
                export const onEvent = async (event, meta) => {
                    await fetch('https://google.com/results.json?query=' + event.event)
                }
            `
            await resetTestDatabase(indexJs)
            const vm = await createReadyPluginConfigVm(hub, pluginConfig39, indexJs)
            const event: ProcessedPluginEvent = {
                ...defaultEvent,
                event: 'export',
            }
            await vm.methods.onEvent!(event)
            expect(fetch).toHaveBeenCalledWith('https://google.com/results.json?query=export', expect.anything())
        })

        test('export default', async () => {
            const indexJs = `
                const MyPlugin = {
                    onEvent: async (event, meta) => {
                        await fetch('https://google.com/results.json?query=' + event.event)
                    }
                }
                export default MyPlugin
            `
            await resetTestDatabase(indexJs)
            const vm = await createReadyPluginConfigVm(hub, pluginConfig39, indexJs)
            const event: ProcessedPluginEvent = {
                ...defaultEvent,
                event: 'default export',
            }
            await vm.methods.onEvent!(event)
            expect(fetch).toHaveBeenCalledWith(
                'https://google.com/results.json?query=default%20export',
                expect.anything()
            )
        })
    })

    test('meta.config', async () => {
        const indexJs = `
            async function processEvent (event, meta) {
                event.properties = meta.config
                return event
            }
        `
        await resetTestDatabase(indexJs)
        const vm = await createReadyPluginConfigVm(hub, pluginConfig39, indexJs)
        const event: PluginEvent = {
            ...defaultEvent,
            event: 'original event',
            properties: {},
        }
        await vm.methods.processEvent!(event)

        expect(event.properties).toEqual(pluginConfig39.config)
    })

    test('meta.cache set/get', async () => {
        const indexJs = `
            async function setupPlugin (meta) {
                await meta.cache.set('counter', 0)
            }
            async function processEvent (event, meta) {
                const counter = await meta.cache.get('counter', 999)
                meta.cache.set('counter', counter + 1)
                event.properties['counter'] = counter + 1
                return event
            }
        `

        await resetTestDatabase(indexJs)
        const vm = await createReadyPluginConfigVm(hub, pluginConfig39, indexJs)
        const event: PluginEvent = {
            ...defaultEvent,
            event: 'original event',
            properties: {},
        }

        await vm.methods.processEvent!(event)
        expect(event.properties!['counter']).toEqual(1)

        await vm.methods.processEvent!(event)
        expect(event.properties!['counter']).toEqual(2)

        await vm.methods.processEvent!(event)
        expect(event.properties!['counter']).toEqual(3)
    })

    test('meta.storage set/get/del', async () => {
        const indexJs = `
            async function setupPlugin (meta) {
                await meta.storage.set('counter', -1)
                const c = await meta.storage.get('counter')
                if (c === -1) {
                    await meta.storage.set('counter', null)
                }
                const c2 = await meta.storage.get('counter')
                if (typeof c === 'undefined') {
                    await meta.storage.set('counter', 0)
                }
            }
            async function processEvent (event, meta) {
                const counter = await meta.storage.get('counter', 999)
                await meta.storage.set('counter', counter + 1)
                event.properties['counter'] = counter + 1

                await meta.storage.set('deleteme', 10)
                await meta.storage.del('deleteme')
                const deleteMeResult = await meta.storage.get('deleteme', null)
                event.properties['deleteme'] = deleteMeResult

                return event
            }
        `

        await resetTestDatabase(indexJs)
        const vm = await createReadyPluginConfigVm(hub, pluginConfig39, indexJs)
        const event: PluginEvent = {
            ...defaultEvent,
            event: 'original event',
            properties: {},
        }

        await vm.methods.processEvent!(event)
        expect(event.properties!['counter']).toEqual(1)
        expect(event.properties!['deleteme']).toEqual(null)

        await vm.methods.processEvent!(event)
        expect(event.properties!['counter']).toEqual(2)

        await vm.methods.processEvent!(event)
        expect(event.properties!['counter']).toEqual(3)
    })

    test('meta.cache expire', async () => {
        const indexJs = `
            async function setupPlugin(meta) {
                await meta.cache.set('counter', 0)
            }
            async function processEvent (event, meta) {
                const counter = await meta.cache.get('counter', 0)
                await meta.cache.set('counter', counter + 1)
                await meta.cache.expire('counter', 1)
                event.properties['counter'] = counter + 1
                return event
            }
        `

        await resetTestDatabase(indexJs)
        const vm = await createReadyPluginConfigVm(hub, pluginConfig39, indexJs)
        const event: PluginEvent = {
            ...defaultEvent,
            event: 'original event',
            properties: {},
        }

        await vm.methods.processEvent!(event)
        expect(event.properties!['counter']).toEqual(1)

        await vm.methods.processEvent!(event)
        expect(event.properties!['counter']).toEqual(2)

        await delay(1200)

        await vm.methods.processEvent!(event)
        expect(event.properties!['counter']).toEqual(1)
    })

    test('meta.cache set ttl', async () => {
        const indexJs = `
            async function setupPlugin(meta) {
                await meta.cache.set('counter', 0)
            }
            async function processEvent (event, meta) {
                const counter = await meta.cache.get('counter', 0)
                await meta.cache.set('counter', counter + 1, 1)
                event.properties['counter'] = counter + 1
                return event
            }
        `

        await resetTestDatabase(indexJs)
        const vm = await createReadyPluginConfigVm(hub, pluginConfig39, indexJs)
        const event: PluginEvent = {
            ...defaultEvent,
            event: 'original event',
            properties: {},
        }

        await vm.methods.processEvent!(event)
        expect(event.properties!['counter']).toEqual(1)

        await vm.methods.processEvent!(event)
        expect(event.properties!['counter']).toEqual(2)

        await delay(1200)

        await vm.methods.processEvent!(event)
        expect(event.properties!['counter']).toEqual(1)
    })

    test('meta.cache incr', async () => {
        const indexJs = `
            async function setupPlugin(meta) {
                await meta.cache.set('counter', 0)
            }
            async function processEvent (event, meta) {
                const counter = await meta.cache.incr('counter')
                event.properties['counter'] = counter
                return event
            }
        `

        await resetTestDatabase(indexJs)
        const vm = await createReadyPluginConfigVm(hub, pluginConfig39, indexJs)
        const event: PluginEvent = {
            ...defaultEvent,
            event: 'original event',
            properties: {},
        }

        await vm.methods.processEvent!(event)
        expect(event.properties!['counter']).toEqual(1)

        await vm.methods.processEvent!(event)
        expect(event.properties!['counter']).toEqual(2)

        await vm.methods.processEvent!(event)
        expect(event.properties!['counter']).toEqual(3)
    })

    test('meta.cache lpush/lrange/llen', async () => {
        const indexJs = `
            async function setupPlugin (meta) {
                await meta.cache.lpush('mylist', 'a string')
                await meta.cache.lpush('mylist', ['an', 'array'])

            }
            async function processEvent (event, meta) {
                const mylistBefore = await meta.cache.lrange('mylist', 0, 3)
                const mylistLen = await meta.cache.llen('mylist')
                event.properties['mylist_before'] = mylistBefore
                event.properties['mylist_len'] = mylistLen
                await meta.cache.expire('mylist', 0)
                const mylistAfter = await meta.cache.lrange('mylist', 0, 3)
                event.properties['mylist_after'] = mylistAfter
                return event
            }

        `

        await resetTestDatabase(indexJs)
        const vm = await createReadyPluginConfigVm(hub, pluginConfig39, indexJs)
        const event: PluginEvent = {
            ...defaultEvent,
            event: 'original event',
            properties: {},
        }

        await vm.methods.processEvent!(event)
        expect(event.properties!['mylist_before']).toEqual(expect.arrayContaining(['a string', 'an', 'array']))
        expect(event.properties!['mylist_len']).toEqual(3)
        expect(event.properties!['mylist_after']).toEqual([])
    })

    test('meta.cache lrem/lpop/lpush/lrange', async () => {
        const indexJs = `
            async function setupPlugin (meta) {
                await meta.cache.lpush('mylist2', ['1', '2', '3'])

            }
            async function processEvent (event, meta) {
                const mylistBefore = await meta.cache.lrange('mylist2', 0, 3)
                event.properties['mylist_before'] = mylistBefore

                const poppedElements = await meta.cache.lpop('mylist2', 1)
                event.properties['popped_elements'] = poppedElements

                const myListAfterLpop = await meta.cache.lrange('mylist2', 0, 3)
                event.properties['mylist_after_lpop'] = myListAfterLpop

                const removedElementsCount = await meta.cache.lrem('mylist2', 1, '2')
                event.properties['removed_elements_count'] = removedElementsCount

                const myListAfterLrem = await meta.cache.lrange('mylist2', 0, 3)
                event.properties['mylist_after_lrem'] = myListAfterLrem

                await meta.cache.expire('mylist2', 0)

                return event
            }

        `

        await resetTestDatabase(indexJs)
        const vm = await createReadyPluginConfigVm(hub, pluginConfig39, indexJs)
        const event: PluginEvent = {
            ...defaultEvent,
            event: 'original event',
            properties: {},
        }

        await vm.methods.processEvent!(event)
        expect(event.properties!['mylist_before']).toEqual(expect.arrayContaining(['1', '2', '3']))
        expect(event.properties!['popped_elements']).toEqual(['3'])
        expect(event.properties!['mylist_after_lpop']).toEqual(expect.arrayContaining(['1', '2']))
        expect(event.properties!['removed_elements_count']).toEqual(1)
        expect(event.properties!['mylist_after_lrem']).toEqual(['1'])
    })

    test('console.log', async () => {
        const indexJs = `
            async function processEvent (event, meta) {
                console.log(event.event)
                return event
            }
        `
        await resetTestDatabase(indexJs)
        const vm = await createReadyPluginConfigVm(hub, { ...pluginConfig39, plugin: plugin60 }, indexJs)
        const event: PluginEvent = {
            ...defaultEvent,
            event: 'logged event',
        }

        await vm.methods.processEvent!(event)

        expect(mockProducerObserver.produceSpy).toHaveBeenCalledTimes(1)
        expect(mockProducerObserver.getParsedQueuedMessages()[0]).toEqual({
            topic: KAFKA_PLUGIN_LOG_ENTRIES,
            messages: [
                {
                    key: expect.any(String),
                    value: {
                        id: expect.any(String),
                        instance_id: hub.instanceId.toString(),
                        message: 'logged event',
                        plugin_config_id: pluginConfig39.id,
                        plugin_id: pluginConfig39.plugin_id,
                        source: PluginLogEntrySource.Console,
                        team_id: pluginConfig39.team_id,
                        timestamp: expect.any(String),
                        type: PluginLogEntryType.Log,
                    },
                },
            ],
        })
    })

    test('fetch', async () => {
        const indexJs = `
            async function processEvent (event, meta) {
                const response = await fetch('https://google.com/results.json?query=' + event.event)
                event.properties = await response.json()
                return event
            }
        `
        await resetTestDatabase(indexJs)
        const vm = await createReadyPluginConfigVm(hub, pluginConfig39, indexJs)
        const event: PluginEvent = {
            ...defaultEvent,
            event: 'fetched',
        }

        await vm.methods.processEvent!(event)
        expect(fetch).toHaveBeenCalledWith('https://google.com/results.json?query=fetched', expect.anything())

        expect(event.properties).toEqual({ count: 2, query: 'bla', results: [true, true] })
    })

    test('fetch via import', async () => {
        const indexJs = `
            import importedFetch from 'node-fetch'
            async function processEvent (event, meta) {
                const response = await importedFetch('https://google.com/results.json?query=' + event.event)
                event.properties = await response.json()
                return event
            }
        `
        await resetTestDatabase(indexJs)
        const vm = await createReadyPluginConfigVm(hub, pluginConfig39, indexJs)
        const event: PluginEvent = {
            ...defaultEvent,
            event: 'fetched',
        }

        await vm.methods.processEvent!(event)
        expect(fetch).toHaveBeenCalledWith('https://google.com/results.json?query=fetched', expect.anything())

        expect(event.properties).toEqual({ count: 2, query: 'bla', results: [true, true] })
    })

    test('fetch via require', async () => {
        const indexJs = `
            async function processEvent (event, meta) {
                const response = await require('node-fetch')('https://google.com/results.json?query=' + event.event)
                event.properties = await response.json()
                return event
            }
        `
        await resetTestDatabase(indexJs)
        const vm = await createReadyPluginConfigVm(hub, pluginConfig39, indexJs)
        const event: PluginEvent = {
            ...defaultEvent,
            event: 'fetched',
        }

        await vm.methods.processEvent!(event)
        expect(fetch).toHaveBeenCalledWith('https://google.com/results.json?query=fetched', expect.anything())

        expect(event.properties).toEqual({ count: 2, query: 'bla', results: [true, true] })
    })

    test('posthog.api', async () => {
        const indexJs = `
            async function processEvent (event, meta) {
                event.properties = {}
                const getResponse = await posthog.api.get('/api/event')
                event.properties.get = await getResponse.json()
                await posthog.api.get('/api/event', { data: { url: 'param' } })
                await posthog.api.post('/api/event', { data: { a: 1 }})
                await posthog.api.put('/api/event', { data: { b: 2 } })
                await posthog.api.patch('/api/event', { data: { c: 3 }})
                await posthog.api.delete('/api/event')

                // test auth defaults override
                await posthog.api.get('/api/event', { projectApiKey: 'token', personalApiKey: 'secret' })

                // test replace @current with team id
                await posthog.api.get('/api/projects/@current/event')

                return event
            }
        `
        await resetTestDatabase(indexJs)
        const vm = await createReadyPluginConfigVm(hub, pluginConfig39, indexJs)
        const event: PluginEvent = {
            ...defaultEvent,
            event: 'fetched',
        }

        await vm.methods.processEvent!(event)

        expect(event.properties?.get).toEqual({ hello: 'world' })
        expect((fetch as any).mock.calls.length).toEqual(8)

        // eslint-disable-next-line no-restricted-syntax
        const details = JSON.parse(JSON.stringify((fetch as any).mock.calls))
        expect(details).toMatchObject([
            [
                'https://app.posthog.com/api/event?token=THIS+IS+NOT+A+TOKEN+FOR+TEAM+2',
                {
                    headers: { Authorization: expect.stringContaining('Bearer phx_') },
                    method: 'GET',
                },
            ],
            [
                'https://app.posthog.com/api/event?url=param&token=THIS+IS+NOT+A+TOKEN+FOR+TEAM+2',
                {
                    headers: { Authorization: expect.stringContaining('Bearer phx_') },
                    method: 'GET',
                },
            ],
            [
                'https://app.posthog.com/api/event?token=THIS+IS+NOT+A+TOKEN+FOR+TEAM+2',
                {
                    headers: {
                        Authorization: expect.stringContaining('Bearer phx_'),
                        'Content-Type': 'application/json',
                    },
                    method: 'POST',
                    body: JSON.stringify({ a: 1 }),
                },
            ],
            [
                'https://app.posthog.com/api/event?token=THIS+IS+NOT+A+TOKEN+FOR+TEAM+2',
                {
                    headers: { Authorization: expect.stringContaining('Bearer phx_') },
                    method: 'PUT',
                    body: JSON.stringify({ b: 2 }),
                },
            ],
            [
                'https://app.posthog.com/api/event?token=THIS+IS+NOT+A+TOKEN+FOR+TEAM+2',
                {
                    headers: {
                        Authorization: expect.stringContaining('Bearer phx_'),
                        'Content-Type': 'application/json',
                    },
                    method: 'PATCH',
                    body: JSON.stringify({ c: 3 }),
                },
            ],
            [
                'https://app.posthog.com/api/event?token=THIS+IS+NOT+A+TOKEN+FOR+TEAM+2',
                {
                    headers: { Authorization: expect.stringContaining('Bearer phx_') },
                    method: 'DELETE',
                },
            ],
            [
                'https://app.posthog.com/api/event?token=token',
                {
                    headers: { Authorization: 'Bearer secret' },
                    method: 'GET',
                },
            ],
            [
                'https://app.posthog.com/api/projects/' +
                    pluginConfig39.team_id +
                    '/event?token=THIS+IS+NOT+A+TOKEN+FOR+TEAM+2',
                {
                    headers: { Authorization: expect.stringContaining('Bearer phx_') },
                    method: 'GET',
                },
            ],
        ])
    })

    test('attachments', async () => {
        const indexJs = `
            async function processEvent (event, meta) {
                event.properties = meta.attachments
                return event
            }
        `
        const attachments = {
            attachedFile: {
                content_type: 'application/json',
                file_name: 'plugin.json',
                contents: Buffer.from('{"name": "plugin"}'),
            },
        }
        const vm = await createReadyPluginConfigVm(
            hub,
            {
                ...pluginConfig39,
                attachments,
            },
            indexJs
        )
        const event: PluginEvent = {
            ...defaultEvent,
            event: 'attachments',
        }

        await vm.methods.processEvent!(event)

        expect(event.properties).toEqual(attachments)
    })

    test('onEvent', async () => {
        const indexJs = `
            async function onEvent (event, meta) {
                await fetch('https://google.com/results.json?query=' + event.event)
            }
        `
        await resetTestDatabase(indexJs)
        const vm = await createReadyPluginConfigVm(hub, pluginConfig39, indexJs)
        const event: ProcessedPluginEvent = {
            ...defaultEvent,
            event: 'onEvent',
        }
        await vm.methods.onEvent!(event)
        expect(fetch).toHaveBeenCalledWith('https://google.com/results.json?query=onEvent', expect.anything())
    })

    test('imports', async () => {
        const indexJs = `
            const urlImport = require('url');
            async function processEvent (event, meta) {
                event.properties = {
                    imports: {
                        // Injected because it was imported
                        url: 'URL' in urlImport,

                        // Available via plugin host imports because it was imported
                        urlViaPluginHostImports: 'URL' in __pluginHostImports.url,

                        // Not in plugin host imports because it was not imported
                        cryptoUndefined: __pluginHostImports.crypto === undefined,
                    },
                }
                return event
            }
        `
        await resetTestDatabase(indexJs)
        const vm = await createReadyPluginConfigVm(hub, pluginConfig39, indexJs)
        const event = await vm.methods.processEvent!({ ...defaultEvent })

        expect(event?.properties?.imports).toEqual({
            url: true,
            urlViaPluginHostImports: true,
            cryptoUndefined: true,
        })
    })
})
