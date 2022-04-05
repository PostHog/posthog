import http from 'http'

import { startPluginsServer } from '../src/main/pluginsServer'
import { HTTP_SERVER_PORTS } from '../src/main/services/http-server'
import { LogLevel, PluginServerMode } from '../src/types'
import { makePiscina } from '../src/worker/piscina'
import { resetTestDatabase } from './helpers/sql'

jest.mock('../src/main/job-queues/job-queue-consumer')
jest.mock('../src/main/services/schedule')
jest.mock('../src/utils/db/sql')

jest.setTimeout(60000) // 60 sec timeout

describe('http server', () => {
    beforeEach(async () => {
        const testCode = `
            async function processEvent (event) {
                return event
            }
        `

        await resetTestDatabase(testCode)
    })

    describe('ingestion server', () => {
        test('_ready', async () => {
            const pluginsServer = await startPluginsServer(
                {
                    WORKER_CONCURRENCY: 2,
                    STALENESS_RESTART_SECONDS: 5,
                    LOG_LEVEL: LogLevel.Debug,
                    DISABLE_HTTP_SERVER: false,
                },
                makePiscina,
                PluginServerMode.Ingestion
            )

            const port = HTTP_SERVER_PORTS[PluginServerMode.Ingestion]
            http.get(`http://localhost:${port}/_ready`, (res) => {
                const { statusCode } = res
                expect(statusCode).toEqual(200)
            })

            await pluginsServer.stop()
        })
    })
})

describe('runner server', () => {
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
            makePiscina,
            PluginServerMode.Runner
        )

        const port = HTTP_SERVER_PORTS[PluginServerMode.Runner]

        http.get(`http://localhost:${port}/_ready`, (res) => {
            const { statusCode } = res
            expect(statusCode).toEqual(200)
        })

        await pluginsServer.stop()
    })
})
