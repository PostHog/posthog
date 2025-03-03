import http from 'http'

import { DEFAULT_HTTP_SERVER_PORT } from '../src/config/config'
import { PluginServer } from '../src/server'
import { PluginServerMode } from '../src/types'
import { resetTestDatabase } from './helpers/sql'

jest.mock('../src/utils/status')
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

describe('router', () => {
    let server: PluginServer

    beforeAll(async () => {
        jest.spyOn(process, 'exit').mockImplementation(() => {})

        server = new PluginServer({
            PLUGIN_SERVER_MODE: PluginServerMode.ingestion_v2,
        })
        await server.start()
    })

    afterAll(async () => {
        await server.stop()
    })

    // these should simply pass under normal conditions
    describe('health and readiness checks', () => {
        test('_health', async () => {
            await resetTestDatabase()
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
