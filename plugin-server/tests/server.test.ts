import * as Sentry from '@sentry/node'

import { startPluginsServer } from '../src/main/pluginsServer'
import { LogLevel } from '../src/types'
import { killProcess } from '../src/utils/kill'
import { delay } from '../src/utils/utils'
import { makePiscina } from '../src/worker/piscina'
import { resetTestDatabase } from './helpers/sql'

jest.mock('@sentry/node')
jest.mock('../src/utils/db/sql')
jest.mock('../src/utils/kill')
jest.setTimeout(60000) // 60 sec timeout

test('startPluginsServer', async () => {
    const testCode = `
        async function processEvent (event) {
            return event
        }
    `
    await resetTestDatabase(testCode)
    const pluginsServer = await startPluginsServer(
        {
            WORKER_CONCURRENCY: 2,
            LOG_LEVEL: LogLevel.Debug,
        },
        makePiscina
    )

    await pluginsServer.stop()
})

describe('plugin server staleness check', () => {
    test('test if the server terminates', async () => {
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
                },
            }
        )

        await pluginsServer.stop()
    })
})
