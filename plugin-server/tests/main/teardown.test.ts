import ClickHouse from '@posthog/clickhouse'
import { PluginEvent } from '@posthog/plugin-scaffold'

import { waitForExpect } from '../../functional_tests/expectations'
import { startPluginsServer } from '../../src/main/pluginsServer'
import { Hub, LogLevel, PluginLogEntry, PluginLogEntrySource, PluginLogEntryType } from '../../src/types'
import { EventPipelineRunner } from '../../src/worker/ingestion/event-pipeline/runner'
import { EventsProcessor } from '../../src/worker/ingestion/process-event'
import { pluginConfig39 } from '../helpers/plugins'
import { resetTestDatabase } from '../helpers/sql'

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

async function getLogEntriesForPluginConfig(hub: Hub, pluginConfigId: number) {
    const { data: logEntries } = (await hub.clickhouse.querying(`
        SELECT *
        FROM plugin_log_entries
        WHERE 
            plugin_config_id = ${pluginConfigId} AND
            instance_id = '${hub.instanceId}'
        ORDER BY timestamp`)) as unknown as ClickHouse.ObjectQueryResult<PluginLogEntry>
    return logEntries
}

describe('teardown', () => {
    const processEvent = async (hub: Hub, event: PluginEvent) => {
        const result = await new EventPipelineRunner(hub, event, new EventsProcessor(hub)).runEventPipeline(event)
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
            undefined
        )

        await processEvent(hub!, defaultEvent)

        await stop!()

        // verify the teardownPlugin code runs -- since we're reading from
        // ClickHouse, we need to give it a bit of time to have consumed from
        // the topic and written everything we're looking for to the table
        await waitForExpect(async () => {
            const logEntries = await getLogEntriesForPluginConfig(hub!, pluginConfig39.id)

            const systemErrors = logEntries.filter(
                (logEntry) =>
                    logEntry.source == PluginLogEntrySource.System && logEntry.type == PluginLogEntryType.Error
            )
            expect(systemErrors).toHaveLength(1)
            expect(systemErrors[0].message).toContain('Plugin failed to unload')

            const pluginErrors = logEntries.filter(
                (logEntry) =>
                    logEntry.source == PluginLogEntrySource.Plugin && logEntry.type == PluginLogEntryType.Error
            )
            expect(pluginErrors).toHaveLength(1)
            expect(pluginErrors[0].message).toContain('This Happened In The Teardown Palace')
        })
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
        const { hub, stop } = await startPluginsServer(
            {
                WORKER_CONCURRENCY: 2,
                LOG_LEVEL: LogLevel.Log,
            },
            undefined
        )

        await stop!()

        // verify the teardownPlugin code runs -- since we're reading from
        // ClickHouse, we need to give it a bit of time to have consumed from
        // the topic and written everything we're looking for to the table
        await waitForExpect(async () => {
            const logEntries = await getLogEntriesForPluginConfig(hub!, pluginConfig39.id)

            const systemLogs = logEntries.filter((logEntry) => logEntry.source == PluginLogEntrySource.System)
            expect(systemLogs).toHaveLength(2)
            expect(systemLogs[0].message).toContain('Plugin loaded')
            expect(systemLogs[1].message).toContain('Plugin unloaded')

            // verify the teardownPlugin code doesn't run, because processEvent was never called
            // and thus the plugin was never setup - see LazyVM
            const pluginErrors = logEntries.filter(
                (logEntry) =>
                    logEntry.source == PluginLogEntrySource.Plugin && logEntry.type == PluginLogEntryType.Error
            )
            expect(pluginErrors).toHaveLength(0)
        })
    })
})
