import { PluginEvent } from '@posthog/plugin-scaffold'

import { startPluginsServer } from '../../src/main/pluginsServer'
import { LogLevel } from '../../src/types'
import { delay } from '../../src/utils/utils'
import { workerTasks } from '../../src/worker/tasks'
import { pluginConfig39 } from '../helpers/plugins'
import { getErrorForPluginConfig, resetTestDatabase } from '../helpers/sql'

jest.mock('../../src/utils/status')
jest.setTimeout(60000) // 60 sec timeout

const defaultEvent = {
    distinct_id: 'my_id',
    ip: '127.0.0.1',
    site_url: 'http://localhost',
    team_id: 2,
    now: new Date().toISOString(),
    event: 'default event',
    properties: { key: 'value' },
}

describe('teardown', () => {
    const processEvent = async (event: PluginEvent) => {
        const result = await workerTasks['runEventPipeline']({ event })
        const resultEvent = result.args[0]
        return resultEvent
    }

    test('teardown code runs when stopping', async () => {
        await resetTestDatabase(`
            async function processEvent (event) {
                event.properties.processed = 'hell yes'
                event.properties.upperUuid = event.properties.uuid?.toUpperCase()
                return event
            }
            async function teardownPlugin() {
                throw new Error('This Happened In The Teardown Palace')
            }
        `)
        const { stop } = await startPluginsServer({
            WORKER_CONCURRENCY: 2,
            LOG_LEVEL: LogLevel.Log,
        })

        const error1 = await getErrorForPluginConfig(pluginConfig39.id)
        expect(error1).toBe(null)

        await processEvent(defaultEvent)

        await stop()

        // verify the teardownPlugin code runs
        const error2 = await getErrorForPluginConfig(pluginConfig39.id)
        expect(error2.message).toBe('This Happened In The Teardown Palace')
    })

    test('no need to tear down if plugin was never setup', async () => {
        await resetTestDatabase(`
            async function processEvent (event) {
                event.properties.processed = 'hell yes'
                event.properties.upperUuid = event.properties.uuid?.toUpperCase()
                return event
            }
            async function teardownPlugin() {
                throw new Error('This Happened In The Teardown Palace')
            }
        `)
        const { stop } = await startPluginsServer({
            WORKER_CONCURRENCY: 2,
            LOG_LEVEL: LogLevel.Log,
        })

        const error1 = await getErrorForPluginConfig(pluginConfig39.id)
        expect(error1).toBe(null)

        await stop()

        // verify the teardownPlugin code doesn't run, because processEvent was never called
        // and thus the plugin was never setup - see LazyVM
        const error2 = await getErrorForPluginConfig(pluginConfig39.id)
        expect(error2).toBe(null)
    })

    test('teardown code runs when reloading', async () => {
        await resetTestDatabase(`
            async function processEvent (event, meta) {
                event.properties.storage = await meta.storage.get('storage', 'nope')
                return event
            }
            async function teardownPlugin(meta) {
                await meta.storage.set('storage', 'tore down')
            }
        `)
        const { stop, hub } = await startPluginsServer({
            WORKER_CONCURRENCY: 2,
            LOG_LEVEL: LogLevel.Log,
        })

        const error1 = await getErrorForPluginConfig(pluginConfig39.id)
        expect(error1).toBe(null)

        await delay(100)

        await hub.db.postgresQuery(
            'update posthog_pluginconfig set updated_at = now() where id = $1',
            [pluginConfig39.id],
            'testTag'
        )
        const event1 = await processEvent(defaultEvent)
        expect(event1.properties.storage).toBe('nope')

        await delay(10000)

        // const event2 = await piscina!.run({ task: 'runEventPipeline', args: { event: { ...defaultEvent } } })
        const event2 = await processEvent(defaultEvent)
        expect(event2.properties.storage).toBe('tore down')

        await stop()
    })
})
