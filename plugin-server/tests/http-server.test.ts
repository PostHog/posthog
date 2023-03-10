import http from 'http'

import { startPluginsServer } from '../src/main/pluginsServer'
import { HTTP_SERVER_PORT } from '../src/main/services/http-server'
import { makePiscina } from '../src/worker/piscina'

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

let pluginServer

beforeAll(async () => {
    pluginServer = await startPluginsServer(
        {
            WORKER_CONCURRENCY: 0,
        },
        makePiscina,
        { http: true, ingestion: true }
    )
})

afterAll(async () => {
    await pluginServer.stop()
})

describe('http server', () => {
    // these should simply pass under normal conditions
    describe('health and readiness checks', () => {
        test('_health', async () => {
            await new Promise((resolve) =>
                http.get(`http://localhost:${HTTP_SERVER_PORT}/_health`, (res) => {
                    const { statusCode } = res
                    expect(statusCode).toEqual(200)
                    resolve(null)
                })
            )
        })

        test('_ready', async () => {
            await new Promise((resolve) =>
                http.get(`http://localhost:${HTTP_SERVER_PORT}/_ready`, (res) => {
                    const { statusCode } = res
                    expect(statusCode).toEqual(200)
                    resolve(null)
                })
            )

            expect(pluginServer.queue?.consumerReady).toBeTruthy()
            await pluginServer.stop()
        })
    })
})
