// Serial: resets the shared test database and starts a server with shared Kafka/ClickHouse dependencies.
import { PluginServerMode } from '../src/common/config'
import { IngestionGeneralServer } from '../src/servers/ingestion-general-server'
import { TEST_KAFKA_TOPICS, ensureKafkaTopics } from './helpers/kafka'
import { resetTestDatabase } from './helpers/sql'

jest.setTimeout(20000) // 20 sec timeout - longer indicates an issue

describe('ingestion general server', () => {
    jest.retryTimes(3, { logErrorsBeforeRetry: true }) // Flakey due to reliance on kafka/clickhouse
    let server: IngestionGeneralServer | null = null

    beforeAll(async () => {
        // Every consumer verifies its output topics at startup and fails if one is missing.
        // Redpanda auto-creates a topic on the first producer metadata request, but that same
        // request reports the topic as missing, so on a fresh broker the first start fails.
        // Create the whole set up front rather than relying on topics earlier test files left.
        await ensureKafkaTopics(TEST_KAFKA_TOPICS)
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
            // The AI consumer requires a personhog client; the gRPC connection
            // is lazy, so startup doesn't need a live router.
            PERSONHOG_ENABLED: true,
            PERSONHOG_ADDR: 'localhost:50052',
        })
        await server.start()
        expect(process.exit).not.toHaveBeenCalledWith(1)
    })
})
