// eslint-disable-next-line simple-import-sort/imports
import { mockProducerObserver } from '../../tests/helpers/mocks/producer.mock'

import { PluginEvent } from '@posthog/plugin-scaffold'

import { PluginServer } from '../../src/server'
import {
    Hub,
    LogLevel,
    PluginLogEntrySource,
    PluginLogEntryType,
    PluginServerMode,
    ProjectId,
    Team,
} from '../../src/types'
import { EventPipelineRunner } from '../../src/worker/ingestion/event-pipeline/runner'
import { MeasuringPersonsStoreForDistinctIdBatch } from '../../src/worker/ingestion/persons/measuring-person-store'
import { resetTestDatabase } from '../helpers/sql'
import { v4 } from 'uuid'
import { BatchWritingGroupStoreForBatch } from '../../src/worker/ingestion/groups/batch-writing-group-store'

jest.setTimeout(10000)

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

const team: Team = {
    id: 2,
    api_token: 'api_token',
    person_processing_opt_out: null,
    project_id: 2 as ProjectId,
    organization_id: '2',
    uuid: v4(),
    name: '2',
    anonymize_ips: true,
    slack_incoming_webhook: 'slack_incoming_webhook',
    session_recording_opt_in: true,
    heatmaps_opt_in: null,
    ingested_event: true,
    person_display_name_properties: null,
    test_account_filters: null,
    cookieless_server_hash_mode: null,
    timezone: 'UTC',
    available_features: [],
}

describe('teardown', () => {
    beforeEach(async () => {
        jest.spyOn(process, 'exit').mockImplementation()

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
    })

    const processEvent = async (hub: Hub, event: PluginEvent) => {
        const personsStoreForDistinctId = new MeasuringPersonsStoreForDistinctIdBatch(
            hub.db,
            String(event.team_id),
            event.distinct_id
        )
        const groupStoreForBatch = new BatchWritingGroupStoreForBatch(hub.db)
        const result = await new EventPipelineRunner(
            hub,
            event,
            null,
            [],
            personsStoreForDistinctId,
            groupStoreForBatch
        ).runEventPipeline(event, team)
        const resultEvent = result.args[0]
        return resultEvent
    }

    it('teardown code runs when stopping', async () => {
        const server = new PluginServer({
            PLUGIN_SERVER_MODE: PluginServerMode.ingestion_v2,
            LOG_LEVEL: LogLevel.Info,
        })
        await server.start()

        await processEvent(server.hub!, defaultEvent)
        await server.stop()

        const logEntries = mockProducerObserver.getProducedKafkaMessagesForTopic('plugin_log_entries_test')

        const systemErrors = logEntries.filter(
            (logEntry) =>
                logEntry.value.source == PluginLogEntrySource.System && logEntry.value.type == PluginLogEntryType.Error
        )
        expect(systemErrors).toHaveLength(1)
        expect(systemErrors[0].value.message).toContain('Plugin failed to unload')

        const pluginErrors = logEntries.filter(
            (logEntry) =>
                logEntry.value.source == PluginLogEntrySource.Plugin && logEntry.value.type == PluginLogEntryType.Error
        )
        expect(pluginErrors).toHaveLength(1)
        expect(pluginErrors[0].value.message).toContain('This Happened In The Teardown Palace')
    })

    it('no need to tear down if plugin was never setup', async () => {
        const server = new PluginServer({
            PLUGIN_SERVER_MODE: PluginServerMode.ingestion_v2,
            LOG_LEVEL: LogLevel.Info,
        })
        await server.start()
        await server.stop()

        const logEntries = mockProducerObserver.getProducedKafkaMessagesForTopic('plugin_log_entries_test')

        // verify the teardownPlugin code runs -- since we're reading from
        // ClickHouse, we need to give it a bit of time to have consumed from
        // the topic and written everything we're looking for to the table

        const systemLogs = logEntries.filter((logEntry) => logEntry.value.source == PluginLogEntrySource.System)
        expect(systemLogs).toHaveLength(2)
        expect(systemLogs[0].value.message).toContain('Plugin loaded')
        expect(systemLogs[1].value.message).toContain('Plugin unloaded')

        // verify the teardownPlugin code doesn't run, because processEvent was never called
        // and thus the plugin was never setup - see LazyVM
        const pluginErrors = logEntries.filter(
            (logEntry) =>
                logEntry.value.source == PluginLogEntrySource.Plugin && logEntry.value.type == PluginLogEntryType.Error
        )
        expect(pluginErrors).toHaveLength(0)
    })
})
