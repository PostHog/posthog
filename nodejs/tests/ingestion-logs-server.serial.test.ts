import { PluginServerMode } from '../src/common/config'
import { IngestionLogsServer } from '../src/servers/ingestion-logs-server'
import { resetTestDatabase } from './helpers/sql'

jest.setTimeout(20000) // 20 sec timeout - longer indicates an issue

describe('ingestion logs server', () => {
    jest.retryTimes(3) // Flakey due to reliance on kafka/clickhouse
    let server: IngestionLogsServer | null = null

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

    it('should not error on startup - ingestion_logs', async () => {
        server = new IngestionLogsServer({
            LOG_LEVEL: 'debug',
            PLUGIN_SERVER_MODE: PluginServerMode.ingestion_logs,
        })
        await server.start()
        expect(process.exit).not.toHaveBeenCalledWith(1)
    })
})
