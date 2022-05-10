import * as Sentry from '@sentry/node'
import * as nodeSchedule from 'node-schedule'

import { ServerInstance, startPluginsServer } from '../src/main/pluginsServer'
import { LogLevel, PluginsServerConfig } from '../src/types'
import { killProcess } from '../src/utils/kill'
import { delay } from '../src/utils/utils'
import { makePiscina } from '../src/worker/piscina'
import { resetTestDatabase } from './helpers/sql'

jest.mock('@sentry/node')
jest.mock('../src/utils/db/sql')
jest.mock('../src/utils/kill')
jest.setTimeout(60000) // 60 sec timeout

function numberOfScheduledJobs() {
    return Object.keys(nodeSchedule.scheduledJobs).length
}

describe('server', () => {
    let pluginsServer: ServerInstance | null = null

    function createPluginServer(config: Partial<PluginsServerConfig> = {}) {
        return startPluginsServer(
            {
                WORKER_CONCURRENCY: 2,
                LOG_LEVEL: LogLevel.Debug,
                ...config,
            },
            makePiscina
        )
    }

    afterEach(async () => {
        await pluginsServer?.stop()
        pluginsServer = null
    })

    test('startPluginsServer does not error', async () => {
        const testCode = `
        async function processEvent (event) {
            return event
        }
    `
        await resetTestDatabase(testCode)
        pluginsServer = await createPluginServer()
    })

    describe('plugin server staleness check', () => {
        test('test if the server terminates', async () => {
            const testCode = `
            async function processEvent (event) {
                return event
            }
        `
            await resetTestDatabase(testCode)

            pluginsServer = await createPluginServer({
                STALENESS_RESTART_SECONDS: 5,
            })

            await delay(10000)

            expect(killProcess).toHaveBeenCalled()

            expect(Sentry.captureMessage).toHaveBeenCalledWith(
                `Plugin Server has not ingested events for over 5 seconds! Rebooting.`,
                {
                    extra: {
                        instanceId: expect.any(String),
                        lastActivity: expect.any(String),
                        lastActivityType: 'serverStart',
                        piscina: expect.any(String),
                        isServerStale: true,
                        timeSinceLastActivity: expect.any(Number),
                    },
                }
            )
        })
    })

    test('starting and stopping node-schedule scheduled jobs', async () => {
        expect(numberOfScheduledJobs()).toEqual(0)

        pluginsServer = await createPluginServer()

        expect(numberOfScheduledJobs()).toBeGreaterThan(1)

        await pluginsServer.stop()
        pluginsServer = null

        expect(numberOfScheduledJobs()).toEqual(0)
    })
})
