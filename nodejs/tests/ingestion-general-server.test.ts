import {
    KAFKA_APP_METRICS_2,
    KAFKA_CLICKHOUSE_HEATMAP_EVENTS,
    KAFKA_EVENTS_PLUGIN_INGESTION_DLQ,
    KAFKA_INGESTION_WARNINGS,
} from '~/common/config/kafka-topics'

import { PluginServerMode } from '../src/common/config'
import { IngestionGeneralServer } from '../src/servers/ingestion-general-server'
import { ensureKafkaTopics } from './helpers/kafka'
import { resetTestDatabase } from './helpers/sql'

jest.setTimeout(20000) // 20 sec timeout - longer indicates an issue

describe('ingestion general server', () => {
    jest.retryTimes(3) // Flakey due to reliance on kafka/clickhouse
    let server: IngestionGeneralServer | null = null

    beforeAll(async () => {
        // Combined mode starts the clientwarnings and heatmaps consumers, which verify their output
        // topics exist and fail startup if they don't (unlike the analytics consumer, which only
        // logs). Create those topics so the check is deterministic rather than relying on ambient
        // topics left by other tests.
        await ensureKafkaTopics([
            KAFKA_CLICKHOUSE_HEATMAP_EVENTS,
            KAFKA_INGESTION_WARNINGS,
            KAFKA_EVENTS_PLUGIN_INGESTION_DLQ,
            KAFKA_APP_METRICS_2,
        ])
    })

    beforeEach(async () => {
        jest.spyOn(process, 'exit').mockImplementation()

        await resetTestDatabase()
    })

    afterEach(async () => {
        if (server) {
            await server.stop()
            expect(process.exit).toHaveBeenCalledTimes(1)
            expect(process.exit).toHaveBeenCalledWith(0)
            server = null
        }
    })

    it('should not error on startup - ingestion_v2', async () => {
        server = new IngestionGeneralServer({
            LOG_LEVEL: 'debug',
            PLUGIN_SERVER_MODE: PluginServerMode.ingestion_v2,
        })
        await server.start()
        expect(process.exit).not.toHaveBeenCalledWith(1)
    })

    it('should not error on startup - ingestion_v2_combined', async () => {
        server = new IngestionGeneralServer({
            LOG_LEVEL: 'debug',
            PLUGIN_SERVER_MODE: PluginServerMode.ingestion_v2_combined,
        })
        await server.start()
        expect(process.exit).not.toHaveBeenCalledWith(1)
    })
})
