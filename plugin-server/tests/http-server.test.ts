import { startPluginsServer } from '../src/main/pluginsServer'
import { createHttpServer } from '../src/main/services/http-server'
import { LogLevel } from '../src/types'
import { makePiscina } from '../src/worker/piscina'
import { resetTestDatabase } from './helpers/sql'

jest.mock('../src/utils/db/sql')
jest.mock('../src/main/services/http-server')
jest.setTimeout(60000) // 60 sec timeout

describe('http server', () => {
    test('server starts on plugin server startup', async () => {
        const testCode = `
            async function processEvent (event) {
                return event
            }
        `

        await resetTestDatabase(testCode)

        const pluginsServer = await startPluginsServer(
            {
                WORKER_CONCURRENCY: 2,
                STALENESS_RESTART_SECONDS: 5,
                LOG_LEVEL: LogLevel.Debug,
            },
            makePiscina
        )

        expect(createHttpServer).toHaveBeenCalled()

        await pluginsServer.stop()
    })
})
