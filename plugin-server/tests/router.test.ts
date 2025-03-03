import http from 'http'

import { DEFAULT_HTTP_SERVER_PORT } from '../src/config/config'
import { PluginServer } from '../src/server'
import { PluginServerMode } from '../src/types'
import { resetTestDatabase } from './helpers/sql'

jest.setTimeout(10000) // 60 sec timeout

describe('router', () => {
    let server: PluginServer

    beforeAll(async () => {
        process.env.TEST_ENABLE_HTTP = 'true'
        jest.spyOn(process, 'exit').mockImplementation()
        await resetTestDatabase()

        server = new PluginServer({
            PLUGIN_SERVER_MODE: PluginServerMode.ingestion_v2,
        })
        await server.start()
    })

    afterAll(async () => {
        process.env.TEST_ENABLE_HTTP = 'false'
        await server.stop()
    })

    // these should simply pass under normal conditions
    describe('health and readiness checks', () => {
        test('_health', async () => {
            await new Promise((resolve) =>
                http.get(`http://localhost:${DEFAULT_HTTP_SERVER_PORT}/_health`, (res) => {
                    const { statusCode } = res
                    expect(statusCode).toEqual(200)
                    resolve(null)
                })
            )
        })

        test('_ready', async () => {
            await new Promise((resolve) =>
                http.get(`http://localhost:${DEFAULT_HTTP_SERVER_PORT}/_ready`, (res) => {
                    const { statusCode } = res
                    expect(statusCode).toEqual(200)
                    resolve(null)
                })
            )
        })
    })
})
