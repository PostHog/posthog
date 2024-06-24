import { DEFAULT_HTTP_SERVER_PORT } from '../src/config/config'
import { ServerInstance, startPluginsServer } from '../src/main/pluginsServer'
import { makePiscina } from '../src/worker/piscina'
import { resetTestDatabase } from './helpers/sql'

const fetch = jest.requireActual('node-fetch')

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

describe('http server', () => {
    let pluginsServer: ServerInstance | undefined

    beforeEach(async () => {
        const testCode = `
                async function processEvent (event) {
                    return event
                }
            `

        await resetTestDatabase(testCode)
    })

    afterEach(async () => {
        if (pluginsServer) {
            await pluginsServer.stop()
        }
    })
    // these should simply pass under normal conditions
    describe('health and readiness checks', () => {
        test('_health', async () => {
            pluginsServer = await startPluginsServer(
                {
                    WORKER_CONCURRENCY: 0,
                },
                makePiscina,
                { http: true }
            )

            const res = await fetch(`http://localhost:${DEFAULT_HTTP_SERVER_PORT}/_health`)
            expect(res.status).toEqual(200)
            expect(await res.json()).toEqual({ status: 'ok', checks: {} })
        })

        test('_ready', async () => {
            pluginsServer = await startPluginsServer(
                {
                    WORKER_CONCURRENCY: 0,
                },
                makePiscina,
                { http: true, ingestion: true }
            )

            const res = await fetch(`http://localhost:${DEFAULT_HTTP_SERVER_PORT}/_ready`)
            expect(res.status).toEqual(200)
            expect(await res.json()).toEqual({
                status: 'ok',
                checks: {
                    'analytics-ingestion': true,
                },
            })
        })
    })
})
