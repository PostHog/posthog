import { PluginEvent } from '@posthog/plugin-scaffold'

import { startPluginsServer } from '../../src/main/pluginsServer'
import { Hub, LogLevel } from '../../src/types'
import { runEventPipeline } from '../../src/worker/ingestion/event-pipeline/runner'
import { makePiscina } from '../../src/worker/piscina'
import { pluginConfig39 } from '../helpers/plugins'
import { getErrorForPluginConfig, resetTestDatabase } from '../helpers/sql'

jest.mock('../../src/utils/status')
jest.setTimeout(60000) // 60 sec timeout

const defaultEvent: PluginEvent = {
    uuid: '00000000-0000-0000-0000-000000000000',
    distinct_id: 'my_id',
    ip: '127.0.0.1',
    site_url: 'http://localhost',
    team_id: 2,
    now: new Date().toISOString(),
    event: 'default event',
    properties: { key: 'value' },
}

describe('teardown', () => {
    const processEvent = async (hub: Hub, event: PluginEvent) => {
        const result = await runEventPipeline(hub, event)
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
        const { hub, stop } = await startPluginsServer(
            {
                WORKER_CONCURRENCY: 2,
                LOG_LEVEL: LogLevel.Log,
            },
            makePiscina,
            undefined
        )

        const error1 = await getErrorForPluginConfig(pluginConfig39.id)
        expect(error1).toBe(null)

        await processEvent(hub!, defaultEvent)

        await stop?.()

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
        const { stop } = await startPluginsServer(
            {
                WORKER_CONCURRENCY: 2,
                LOG_LEVEL: LogLevel.Log,
            },
            makePiscina,
            undefined
        )

        const error1 = await getErrorForPluginConfig(pluginConfig39.id)
        expect(error1).toBe(null)

        await stop?.()

        // verify the teardownPlugin code doesn't run, because processEvent was never called
        // and thus the plugin was never setup - see LazyVM
        const error2 = await getErrorForPluginConfig(pluginConfig39.id)
        expect(error2).toBe(null)
    })
})
