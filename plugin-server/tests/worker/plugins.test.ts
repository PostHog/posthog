import { PluginEvent } from '@posthog/plugin-scaffold/src/types'

import { Hub, LogLevel } from '../../src/types'
import { processError } from '../../src/utils/db/error'
import { closeHub, createHub } from '../../src/utils/db/hub'
import { delay, IllegalOperationError } from '../../src/utils/utils'
import { loadPlugin } from '../../src/worker/plugins/loadPlugin'
import { runProcessEvent } from '../../src/worker/plugins/run'
import { setupPlugins } from '../../src/worker/plugins/setup'
import { LazyPluginVM } from '../../src/worker/vm/lazy'
import {
    commonOrganizationId,
    mockPluginSourceCode,
    mockPluginTempFolder,
    mockPluginWithSourceFiles,
    plugin60,
    pluginAttachment1,
    pluginConfig39,
} from '../helpers/plugins'
import { resetTestDatabase } from '../helpers/sql'
import { getPluginAttachmentRows, getPluginConfigRows, getPluginRows, setPluginCapabilities } from '../helpers/sqlMock'

jest.mock('../../src/utils/db/sql')
jest.mock('../../src/utils/status')
jest.mock('../../src/utils/db/error')
jest.mock('../../src/worker/plugins/loadPlugin', () => {
    const { loadPlugin } = jest.requireActual('../../src/worker/plugins/loadPlugin')
    return { loadPlugin: jest.fn().mockImplementation(loadPlugin) }
})
jest.setTimeout(20_000)

describe('plugins', () => {
    let hub: Hub

    beforeEach(async () => {
        hub = await createHub({ LOG_LEVEL: LogLevel.Log })
        console.warn = jest.fn() as any
        await resetTestDatabase()
    })

    afterEach(async () => {
        await closeHub(hub)
    })

    test('setupPlugins and runProcessEvent', async () => {
        getPluginRows.mockReturnValueOnce([{ ...plugin60 }])
        getPluginAttachmentRows.mockReturnValueOnce([pluginAttachment1])
        getPluginConfigRows.mockReturnValueOnce([pluginConfig39])

        await setupPlugins(hub)
        const { plugins, pluginConfigs } = hub

        expect(getPluginRows).toHaveBeenCalled()
        expect(getPluginAttachmentRows).toHaveBeenCalled()
        expect(getPluginConfigRows).toHaveBeenCalled()

        expect(Array.from(pluginConfigs.keys())).toEqual([39])

        const pluginConfig = pluginConfigs.get(39)!
        expect(pluginConfig.id).toEqual(pluginConfig39.id)
        expect(pluginConfig.team_id).toEqual(pluginConfig39.team_id)
        expect(pluginConfig.plugin_id).toEqual(pluginConfig39.plugin_id)
        expect(pluginConfig.enabled).toEqual(pluginConfig39.enabled)
        expect(pluginConfig.order).toEqual(pluginConfig39.order)
        expect(pluginConfig.config).toEqual(pluginConfig39.config)

        expect(pluginConfig.plugin).toEqual({
            ...plugin60,
            capabilities: { jobs: [], scheduled_tasks: [], methods: ['processEvent'] },
        })

        expect(pluginConfig.attachments).toEqual({
            maxmindMmdb: {
                content_type: pluginAttachment1.content_type,
                file_name: pluginAttachment1.file_name,
                contents: pluginAttachment1.contents,
            },
        })
        expect(pluginConfig.instance).toBeDefined()
        const instance = pluginConfig.instance!

        expect(instance.getPluginMethod('composeWebhook')).toBeDefined()
        expect(instance.getPluginMethod('getSettings')).toBeDefined()
        expect(instance.getPluginMethod('onEvent')).toBeDefined()
        expect(instance.getPluginMethod('processEvent')).toBeDefined()
        expect(instance.getPluginMethod('setupPlugin')).toBeDefined()
        expect(instance.getPluginMethod('teardownPlugin')).toBeDefined()

        // async loading of capabilities
        expect(setPluginCapabilities).toHaveBeenCalled()
        expect(Array.from(plugins.entries())).toEqual([
            [
                60,
                {
                    ...plugin60,
                    capabilities: { jobs: [], scheduled_tasks: [], methods: ['processEvent'] },
                },
            ],
        ])

        const processEvent = await instance.getPluginMethod('processEvent')
        const event = { event: '$test', properties: {}, team_id: 2 } as PluginEvent
        await processEvent(event)

        expect(event.properties!['processed']).toEqual(true)

        event.properties!['processed'] = false

        const returnedEvent = await runProcessEvent(hub, event)
        expect(event.properties!['processed']).toEqual(true)
        expect(returnedEvent!.properties!['processed']).toEqual(true)
    })

    test('stateless plugins', async () => {
        const plugin = { ...plugin60, is_stateless: true }
        getPluginRows.mockReturnValueOnce([plugin])
        getPluginAttachmentRows.mockReturnValueOnce([pluginAttachment1])
        getPluginConfigRows.mockReturnValueOnce([pluginConfig39, { ...pluginConfig39, id: 40, team_id: 1 }])

        await setupPlugins(hub)
        const { pluginConfigs } = hub

        expect(getPluginRows).toHaveBeenCalled()
        expect(getPluginAttachmentRows).toHaveBeenCalled()
        expect(getPluginConfigRows).toHaveBeenCalled()

        expect(Array.from(pluginConfigs.keys())).toEqual([39, 40])

        const pluginConfigTeam1 = pluginConfigs.get(40)!
        const pluginConfigTeam2 = pluginConfigs.get(39)!

        expect(pluginConfigTeam1.plugin).toEqual(plugin)
        expect(pluginConfigTeam2.plugin).toEqual(plugin)

        expect(pluginConfigTeam1.instance).toBeDefined()
        expect(pluginConfigTeam2.instance).toBeDefined()

        expect(pluginConfigTeam1.instance).toEqual(pluginConfigTeam2.instance)
    })

    test('plugin returns null', async () => {
        getPluginRows.mockReturnValueOnce([
            mockPluginWithSourceFiles('function processEvent (event, meta) { return null }'),
        ])
        getPluginConfigRows.mockReturnValueOnce([pluginConfig39])
        getPluginAttachmentRows.mockReturnValueOnce([])

        await setupPlugins(hub)

        const event = { event: '$test', properties: {}, team_id: 2 } as PluginEvent
        const returnedEvent = await runProcessEvent(hub, event)

        expect(returnedEvent).toEqual(null)
    })

    test('plugin meta has what it should have', async () => {
        getPluginRows.mockReturnValueOnce([
            mockPluginWithSourceFiles(`
            function setupPlugin (meta) { meta.global.key = 'value' }
            function processEvent (event, meta) { event.properties=meta; return event }
        `),
        ])
        getPluginConfigRows.mockReturnValueOnce([pluginConfig39])
        getPluginAttachmentRows.mockReturnValueOnce([pluginAttachment1])

        await setupPlugins(hub)

        const event = { event: '$test', properties: {}, team_id: 2 } as PluginEvent
        const returnedEvent = await runProcessEvent(hub, event)

        expect(Object.keys(returnedEvent!.properties!).sort()).toEqual([
            '$plugins_failed',
            '$plugins_succeeded',
            'attachments',
            'cache',
            'config',
            'geoip',
            'global',
            'jobs',
            'storage',
            'utils',
        ])
        expect(returnedEvent!.properties!['attachments']).toEqual({
            maxmindMmdb: {
                content_type: 'application/octet-stream',
                contents: Buffer.from('test'),
                file_name: 'test.txt',
            },
        })
        expect(returnedEvent!.properties!['config']).toEqual({ localhostIP: '94.224.212.175' })
        expect(returnedEvent!.properties!['global']).toEqual({ key: 'value' })
    })

    test('source files plugin with broken index.js does not do much', async () => {
        // silence some spam
        console.log = jest.fn()
        console.error = jest.fn()

        getPluginRows.mockReturnValueOnce([
            mockPluginWithSourceFiles(`
            function setupPlugin (met
        `),
        ])
        getPluginConfigRows.mockReturnValueOnce([pluginConfig39])
        getPluginAttachmentRows.mockReturnValueOnce([pluginAttachment1])

        await setupPlugins(hub)
        const { pluginConfigs } = hub

        const pluginConfig = pluginConfigs.get(39)!
        expect(pluginConfig.instance).toBeInstanceOf(LazyPluginVM)
        const vm = pluginConfig.instance as LazyPluginVM
        vm.totalInitAttemptsCounter = 20 // prevent more retries
        await delay(4000) // processError is called at end of retries
        expect(await pluginConfig.instance!.getScheduledTasks()).toEqual({})

        const event = { event: '$test', properties: {}, team_id: 2 } as PluginEvent
        const returnedEvent = await runProcessEvent(hub, { ...event })
        expect(returnedEvent).toEqual(event)

        expect(processError).toHaveBeenCalledWith(hub, pluginConfig, expect.any(SyntaxError))
        const error = jest.mocked(processError).mock.calls[0][2]! as Error
        expect(error.message).toContain(': Unexpected token, expected ","')
    })

    test('local plugin with broken index.js does not do much', async () => {
        // silence some spam
        console.log = jest.fn()
        console.error = jest.fn()

        const [plugin, unlink] = mockPluginTempFolder(`function setupPlugin (met`)
        getPluginRows.mockReturnValueOnce([plugin])
        getPluginConfigRows.mockReturnValueOnce([pluginConfig39])
        getPluginAttachmentRows.mockReturnValueOnce([pluginAttachment1])

        await setupPlugins(hub)
        const { pluginConfigs } = hub

        const pluginConfig = pluginConfigs.get(39)!
        expect(pluginConfig.instance).toBeInstanceOf(LazyPluginVM)
        const vm = pluginConfig.instance as LazyPluginVM
        vm!.totalInitAttemptsCounter = 20 // prevent more retries
        await delay(4000) // processError is called at end of retries
        expect(await pluginConfig.instance!.getScheduledTasks()).toEqual({})

        const event = { event: '$test', properties: {}, team_id: 2 } as PluginEvent
        const returnedEvent = await runProcessEvent(hub, { ...event })
        expect(returnedEvent).toEqual(event)

        expect(processError).toHaveBeenCalledWith(hub, pluginConfig, expect.any(SyntaxError))
        const error = jest.mocked(processError).mock.calls[0][2]! as Error
        expect(error.message).toContain(': Unexpected token, expected ","')

        unlink()
    })

    test('plugin changing event.team_id throws error', async () => {
        getPluginRows.mockReturnValueOnce([
            mockPluginWithSourceFiles(`
            function processEvent (event, meta) {
                event.team_id = 400
                return event
            }
        `),
        ])

        getPluginConfigRows.mockReturnValueOnce([pluginConfig39])
        getPluginAttachmentRows.mockReturnValueOnce([])

        await setupPlugins(hub)
        const { pluginConfigs } = hub

        const event = { event: '$test', properties: {}, team_id: 2 } as PluginEvent
        const returnedEvent = await runProcessEvent(hub, event)

        const expectedReturnedEvent = {
            event: '$test',
            properties: {
                $plugins_failed: ['test-maxmind-plugin (39)'],
                $plugins_succeeded: [],
            },
            team_id: 2,
        }
        expect(returnedEvent).toEqual(expectedReturnedEvent)

        expect(processError).toHaveBeenCalledWith(
            hub,
            pluginConfigs.get(39)!,
            new IllegalOperationError('Plugin tried to change event.team_id'),
            expectedReturnedEvent
        )
    })

    test('plugin throwing error does not prevent ingestion and failure is noted in event', async () => {
        // silence some spam
        console.log = jest.fn()
        console.error = jest.fn()

        getPluginRows.mockReturnValueOnce([
            mockPluginWithSourceFiles(`
            function processEvent (event) {
                throw new Error('I always fail!')
            }
        `),
        ])
        getPluginConfigRows.mockReturnValueOnce([pluginConfig39])
        getPluginAttachmentRows.mockReturnValueOnce([pluginAttachment1])

        await setupPlugins(hub)
        const { pluginConfigs } = hub

        expect(await pluginConfigs.get(39)!.instance!.getScheduledTasks()).toEqual({})

        const event = { event: '$test', properties: {}, team_id: 2 } as PluginEvent
        const returnedEvent = await runProcessEvent(hub, { ...event })

        const expectedReturnEvent = {
            ...event,
            properties: {
                $plugins_failed: ['test-maxmind-plugin (39)'],
                $plugins_succeeded: [],
            },
        }
        expect(returnedEvent).toEqual(expectedReturnEvent)
    })

    test('events have property $plugins_succeeded set to the plugins that succeeded', async () => {
        // silence some spam
        console.log = jest.fn()
        console.error = jest.fn()

        getPluginRows.mockReturnValueOnce([
            mockPluginWithSourceFiles(`
            function processEvent (event) {
                return event
            }
        `),
        ])
        getPluginConfigRows.mockReturnValueOnce([pluginConfig39])
        getPluginAttachmentRows.mockReturnValueOnce([pluginAttachment1])

        await setupPlugins(hub)
        const { pluginConfigs } = hub

        expect(await pluginConfigs.get(39)!.instance!.getScheduledTasks()).toEqual({})

        const event = { event: '$test', properties: {}, team_id: 2 } as PluginEvent
        const returnedEvent = await runProcessEvent(hub, { ...event })

        const expectedReturnEvent = {
            ...event,
            properties: {
                $plugins_failed: [],
                $plugins_succeeded: ['test-maxmind-plugin (39)'],
            },
        }
        expect(returnedEvent).toEqual(expectedReturnEvent)
    })

    test('source files plugin with broken plugin.json does not do much', async () => {
        // silence some spam
        console.log = jest.fn()
        console.error = jest.fn()

        getPluginRows.mockReturnValueOnce([
            mockPluginWithSourceFiles(
                `function processEvent (event, meta) { event.properties.processed = true; return event }`,
                '{ broken: "plugin.json" -=- '
            ),
        ])
        getPluginConfigRows.mockReturnValueOnce([pluginConfig39])
        getPluginAttachmentRows.mockReturnValueOnce([pluginAttachment1])

        await setupPlugins(hub)
        const { pluginConfigs } = hub

        expect(processError).toHaveBeenCalledWith(
            hub,
            pluginConfigs.get(39)!,
            `Could not load "plugin.json" for plugin test-maxmind-plugin ID ${plugin60.id} (organization ID ${commonOrganizationId})`
        )

        expect(await pluginConfigs.get(39)!.instance!.getScheduledTasks()).toEqual({})
    })

    test('local plugin with broken plugin.json does not do much', async () => {
        // silence some spam
        console.log = jest.fn()
        console.error = jest.fn()

        const [plugin, unlink] = mockPluginTempFolder(
            `function processEvent (event, meta) { event.properties.processed = true; return event }`,
            '{ broken: "plugin.json" -=- '
        )
        getPluginRows.mockReturnValueOnce([plugin])
        getPluginConfigRows.mockReturnValueOnce([pluginConfig39])
        getPluginAttachmentRows.mockReturnValueOnce([pluginAttachment1])

        await setupPlugins(hub)
        const { pluginConfigs } = hub

        expect(processError).toHaveBeenCalledWith(
            hub,
            pluginConfigs.get(39)!,
            expect.stringContaining('Could not load "plugin.json" for plugin ')
        )
        expect(await pluginConfigs.get(39)!.instance!.getScheduledTasks()).toEqual({})

        unlink()
    })

    test('plugin with http urls must have source files', async () => {
        // silence some spam
        console.log = jest.fn()
        console.error = jest.fn()

        getPluginRows.mockReturnValueOnce([{ ...plugin60, source__index_ts: undefined }])
        getPluginConfigRows.mockReturnValueOnce([pluginConfig39])
        getPluginAttachmentRows.mockReturnValueOnce([pluginAttachment1])

        await setupPlugins(hub)
        const { pluginConfigs } = hub

        expect(pluginConfigs.get(39)!.plugin!.url).toContain('https://')
        expect(processError).toHaveBeenCalledWith(
            hub,
            pluginConfigs.get(39)!,
            `Could not load source code for plugin test-maxmind-plugin ID 60 (organization ID ${commonOrganizationId}). Tried: index.js`
        )
        expect(await pluginConfigs.get(39)!.instance!.getScheduledTasks()).toEqual({})
    })

    test('plugin config order', async () => {
        getPluginRows.mockReturnValueOnce([
            {
                ...plugin60,
                id: 60,
                plugin_type: 'source',
                source__index_ts: `function processEvent(event) {
                event.properties.plugins = [...(event.properties.plugins || []), 60]
                return event
              }`,
            },
            {
                ...plugin60,
                id: 61,
                plugin_type: 'source',
                source__index_ts: `function processEvent(event) {
                event.properties.plugins = [...(event.properties.plugins || []), 61]
                return event
              }`,
            },
            {
                ...plugin60,
                id: 62,
                plugin_type: 'source',
                source__index_ts: `function processEvent(event) {
                event.properties.plugins = [...(event.properties.plugins || []), 62]
                return event
              }`,
            },
        ])
        getPluginAttachmentRows.mockReturnValueOnce([])
        getPluginConfigRows.mockReturnValueOnce([
            { ...pluginConfig39, order: 2 },
            { ...pluginConfig39, plugin_id: 61, id: 40, order: 1 },
            { ...pluginConfig39, plugin_id: 62, id: 41, order: 3 },
        ])

        await setupPlugins(hub)
        const { pluginConfigsPerTeam } = hub

        expect(pluginConfigsPerTeam.get(pluginConfig39.team_id)?.map((c) => [c.id, c.order])).toEqual([
            [40, 1],
            [39, 2],
            [41, 3],
        ])

        const event = { event: '$test', properties: {}, team_id: 2 } as PluginEvent

        const returnedEvent1 = await runProcessEvent(hub, { ...event, properties: { ...event.properties } })
        expect(returnedEvent1!.properties!.plugins).toEqual([61, 60, 62])

        const returnedEvent2 = await runProcessEvent(hub, { ...event, properties: { ...event.properties } })
        expect(returnedEvent2!.properties!.plugins).toEqual([61, 60, 62])
    })

    test('plugin with source files loads capabilities', async () => {
        getPluginRows.mockReturnValueOnce([
            mockPluginWithSourceFiles(`
            function setupPlugin (meta) { meta.global.key = 'value' }
            function processEvent (event, meta) { event.properties={"x": 1}; return event }
        `),
        ])
        getPluginConfigRows.mockReturnValueOnce([pluginConfig39])
        getPluginAttachmentRows.mockReturnValueOnce([pluginAttachment1])

        await setupPlugins(hub)
        const { pluginConfigs } = hub

        const pluginConfig = pluginConfigs.get(39)!

        await (pluginConfig.instance as LazyPluginVM)?.resolveInternalVm
        // async loading of capabilities

        expect(pluginConfig.plugin!.capabilities!.methods!.sort()).toEqual(['processEvent', 'setupPlugin'])
        expect(pluginConfig.plugin!.capabilities!.jobs).toHaveLength(0)
        expect(pluginConfig.plugin!.capabilities!.scheduled_tasks).toHaveLength(0)
    })

    test('plugin with source files loads all capabilities, no random caps', async () => {
        getPluginRows.mockReturnValueOnce([
            mockPluginWithSourceFiles(`
            export function processEvent (event, meta) { event.properties={"x": 1}; return event }
            export function randomFunction (event, meta) { return event}
            export function onEvent (event, meta) { return event }

            export function runEveryHour(meta) {console.log('1')}

            export const jobs = {
                x: (event, meta) => console.log(event)
            }
        `),
        ])
        getPluginConfigRows.mockReturnValueOnce([pluginConfig39])
        getPluginAttachmentRows.mockReturnValueOnce([pluginAttachment1])

        await setupPlugins(hub)
        const { pluginConfigs } = hub

        const pluginConfig = pluginConfigs.get(39)!

        await (pluginConfig.instance as LazyPluginVM)?.resolveInternalVm
        // async loading of capabilities

        expect(pluginConfig.plugin!.capabilities!.methods!.sort()).toEqual(['onEvent', 'processEvent'])
        expect(pluginConfig.plugin!.capabilities!.jobs).toEqual(['x'])
        expect(pluginConfig.plugin!.capabilities!.scheduled_tasks).toEqual(['runEveryHour'])
    })

    test('plugin with source file loads capabilities', async () => {
        const [plugin, unlink] = mockPluginTempFolder(`
        function processEvent (event, meta) { event.properties={"x": 1}; return event }
        function randomFunction (event, meta) { return event}
        function onEvent (event, meta) { return event }
    `)

        getPluginRows.mockReturnValueOnce([plugin])
        getPluginConfigRows.mockReturnValueOnce([pluginConfig39])
        getPluginAttachmentRows.mockReturnValueOnce([pluginAttachment1])

        await setupPlugins(hub)
        const { pluginConfigs } = hub

        const pluginConfig = pluginConfigs.get(39)!

        await (pluginConfig.instance as LazyPluginVM)?.resolveInternalVm
        // async loading of capabilities

        expect(pluginConfig.plugin!.capabilities!.methods!.sort()).toEqual(['onEvent', 'processEvent'])
        expect(pluginConfig.plugin!.capabilities!.jobs).toEqual([])
        expect(pluginConfig.plugin!.capabilities!.scheduled_tasks).toEqual([])

        unlink()
    })

    test('plugin with source code loads capabilities', async () => {
        getPluginRows.mockReturnValueOnce([
            {
                ...mockPluginSourceCode(),
                source__index_ts: `
        function processEvent (event, meta) { event.properties={"x": 1}; return event }
        function randomFunction (event, meta) { return event}
        function onEvent (event, meta) { return event }`,
            },
        ])
        getPluginConfigRows.mockReturnValueOnce([pluginConfig39])
        getPluginAttachmentRows.mockReturnValueOnce([pluginAttachment1])

        await setupPlugins(hub)
        const { pluginConfigs } = hub

        const pluginConfig = pluginConfigs.get(39)!

        await (pluginConfig.instance as LazyPluginVM)?.resolveInternalVm
        // async loading of capabilities

        expect(pluginConfig.plugin!.capabilities!.methods!.sort()).toEqual(['onEvent', 'processEvent'])
        expect(pluginConfig.plugin!.capabilities!.jobs).toEqual([])
        expect(pluginConfig.plugin!.capabilities!.scheduled_tasks).toEqual([])
    })

    test('reloading plugins after config changes', async () => {
        const makePlugin = (id: number, updated_at = '2020-11-02'): any => ({
            ...plugin60,
            id,
            plugin_type: 'source',
            source: setOrderCode(60),
            updated_at,
        })
        const makeConfig = (plugin_id: number, id: number, order: number, updated_at = '2020-11-02'): any => ({
            ...pluginConfig39,
            plugin_id,
            id,
            order,
            updated_at,
        })

        const setOrderCode = (id: number) => {
            return `
            function processEvent(event) {
                if (!event.properties.plugins) { event.properties.plugins = [] }
                event.properties.plugins.push(${id})
                return event
            }
        `
        }

        getPluginRows.mockReturnValue([makePlugin(60), makePlugin(61), makePlugin(62), makePlugin(63)])
        getPluginAttachmentRows.mockReturnValue([])
        getPluginConfigRows.mockReturnValue([
            makeConfig(60, 39, 0),
            makeConfig(61, 41, 1),
            makeConfig(62, 40, 3),
            makeConfig(63, 42, 2),
        ])

        await setupPlugins(hub)

        expect(loadPlugin).toHaveBeenCalledTimes(4)
        expect(Array.from(hub.plugins.keys())).toEqual(expect.arrayContaining([60, 61, 62, 63]))
        expect(Array.from(hub.pluginConfigs.keys())).toEqual(expect.arrayContaining([39, 40, 41, 42]))

        expect(hub.pluginConfigsPerTeam.get(pluginConfig39.team_id)?.map((c) => [c.id, c.order])).toEqual([
            [39, 0],
            [41, 1],
            [42, 2],
            [40, 3],
        ])

        getPluginRows.mockReturnValue([makePlugin(60), makePlugin(61), makePlugin(63, '2021-02-02'), makePlugin(64)])
        getPluginAttachmentRows.mockReturnValue([])
        getPluginConfigRows.mockReturnValue([
            makeConfig(60, 39, 0),
            makeConfig(61, 41, 3, '2021-02-02'),
            makeConfig(63, 42, 2),
            makeConfig(64, 43, 1),
        ])

        await setupPlugins(hub)

        expect(loadPlugin).toHaveBeenCalledTimes(4 + 3)
        expect(Array.from(hub.plugins.keys())).toEqual(expect.arrayContaining([60, 61, 63, 64]))
        expect(Array.from(hub.pluginConfigs.keys())).toEqual(expect.arrayContaining([39, 41, 42, 43]))

        expect(hub.pluginConfigsPerTeam.get(pluginConfig39.team_id)?.map((c) => [c.id, c.order])).toEqual([
            [39, 0],
            [43, 1],
            [42, 2],
            [41, 3],
        ])
    })

    test("capabilities don't reload without changes", async () => {
        getPluginRows.mockReturnValueOnce([{ ...plugin60 }]).mockReturnValueOnce([
            {
                ...plugin60,
                capabilities: { jobs: [], scheduled_tasks: [], methods: ['processEvent'] },
            },
        ]) // updated in DB via first `setPluginCapabilities` call.
        getPluginAttachmentRows.mockReturnValue([pluginAttachment1])
        getPluginConfigRows.mockReturnValue([pluginConfig39])

        await setupPlugins(hub)
        const pluginConfig = hub.pluginConfigs.get(39)!

        await (pluginConfig.instance as LazyPluginVM)?.resolveInternalVm
        // async loading of capabilities
        expect(setPluginCapabilities.mock.calls.length).toBe(1)

        pluginConfig.updated_at = new Date().toISOString()
        // config is changed, but capabilities haven't changed

        await setupPlugins(hub)
        const newPluginConfig = hub.pluginConfigs.get(39)!

        await (newPluginConfig.instance as LazyPluginVM)?.resolveInternalVm
        // async loading of capabilities

        expect(newPluginConfig.plugin).not.toBe(pluginConfig.plugin)
        expect(setPluginCapabilities.mock.calls.length).toBe(1)
        expect(newPluginConfig.plugin!.capabilities).toEqual(pluginConfig.plugin!.capabilities)
    })
})
