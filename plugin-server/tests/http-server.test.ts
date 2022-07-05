import http from 'http'

import { startPluginsServer } from '../src/main/pluginsServer'
import { HTTP_SERVER_PORT } from '../src/main/services/http-server'
import { makePiscina } from '../src/worker/piscina'
import { resetTestDatabase } from './helpers/sql'

jest.mock('../src/utils/status')
jest.mock('../src/utils/db/sql')
jest.mock('../src/main/utils', () => {
    const actual = jest.requireActual('../src/main/utils')
    return {
        ...actual,
        kafkaHealthcheck: async () => {
            await Promise.resolve()
            return [true, null]
        },
    }
})

jest.setTimeout(60000) // 60 sec timeout

describe('http server', () => {
    // these should simply pass under normal conditions
    describe('health and readiness checks', () => {
        test('_health', async () => {
            const testCode = `
                async function processEvent (event) {
                    return event
                }
            `

            await resetTestDatabase(testCode)

            const pluginsServer = await startPluginsServer(
                {
                    WORKER_CONCURRENCY: 0,
                },
                makePiscina,
                { http: true }
            )

            http.get(`http://localhost:${HTTP_SERVER_PORT}/_health`, (res) => {
                const { statusCode } = res
                expect(statusCode).toEqual(200)
            })

            await pluginsServer.stop()
        })

        test('_ready', async () => {
            const testCode = `
                async function processEvent (event) {
                    return event
                }
            `

            await resetTestDatabase(testCode)

            const pluginsServer = await startPluginsServer(
                {
                    WORKER_CONCURRENCY: 0,
                },
                makePiscina,
                { http: true }
            )

            http.get(`http://localhost:${HTTP_SERVER_PORT}/_ready`, (res) => {
                const { statusCode } = res
                expect(statusCode).toEqual(200)
            })

            expect(pluginsServer.queue?.consumerReady).toBeTruthy()
            await pluginsServer.stop()
        })
    })
})
