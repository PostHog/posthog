import http from 'http'

import { startPluginsServer } from '../src/main/pluginsServer'
import { HTTP_SERVER_PORT } from '../src/main/services/http-server'
import { LogLevel } from '../src/types'
import { makePiscina } from '../src/worker/piscina'
import { resetTestDatabase } from './helpers/sql'

jest.mock('../src/utils/db/sql')
jest.setTimeout(60000) // 60 sec timeout

describe('http server', () => {
    test('_ready', async () => {
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

        http.get(`http://localhost:${HTTP_SERVER_PORT}/_ready`, (res) => {
            const { statusCode } = res
            expect(statusCode).toEqual(200)
        })

        await pluginsServer.stop()
    })
})
