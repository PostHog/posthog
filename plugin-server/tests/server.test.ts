import * as Sentry from '@sentry/node'
import * as nodeSchedule from 'node-schedule'

import { startGraphileWorker } from '../src/main/graphile-worker/worker-setup'
import { ServerInstance, startPluginsServer } from '../src/main/pluginsServer'
import { LogLevel, PluginServerCapabilities, PluginsServerConfig } from '../src/types'
import { makePiscina } from '../src/worker/piscina'
import { resetTestDatabase } from './helpers/sql'

jest.mock('../src/utils/kill')
jest.mock('../src/main/graphile-worker/schedule')
jest.mock('../src/main/graphile-worker/worker-setup')
jest.setTimeout(20000) // 20 sec timeout - longer indicates an issue

function numberOfScheduledJobs() {
    return Object.keys(nodeSchedule.scheduledJobs).length
}

describe('server', () => {
    let pluginsServer: Partial<ServerInstance> | null = null

    function createPluginServer(
        config: Partial<PluginsServerConfig> = {},
        capabilities: PluginServerCapabilities | undefined = undefined
    ) {
        return startPluginsServer(
            {
                WORKER_CONCURRENCY: 2,
                LOG_LEVEL: LogLevel.Debug,
                ...config,
            },
            makePiscina,
            capabilities
        )
    }

    beforeEach(() => {
        jest.spyOn(Sentry, 'captureMessage')
    })

    afterEach(async () => {
        await pluginsServer?.stop?.()
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

    test('starting and stopping node-schedule scheduled jobs', async () => {
        expect(numberOfScheduledJobs()).toEqual(0)

        pluginsServer = await createPluginServer()

        expect(numberOfScheduledJobs()).toBeGreaterThan(1)

        await pluginsServer.stop?.()
        pluginsServer = null

        expect(numberOfScheduledJobs()).toEqual(0)
    })

    describe('plugin-server capabilities', () => {
        test('starts all main services by default', async () => {
            pluginsServer = await createPluginServer()

            expect(startGraphileWorker).toHaveBeenCalled()
        })

        test('disabling pluginScheduledTasks', async () => {
            pluginsServer = await createPluginServer(
                {},
                { ingestion: true, pluginScheduledTasks: false, processPluginJobs: true }
            )

            expect(startGraphileWorker).toHaveBeenCalled()
        })

        test('disabling processPluginJobs', async () => {
            pluginsServer = await createPluginServer(
                {},
                { ingestion: true, pluginScheduledTasks: true, processPluginJobs: false }
            )

            expect(startGraphileWorker).toHaveBeenCalled()
        })

        test('disabling processPluginJobs, ingestion, and pluginScheduledTasks', async () => {
            pluginsServer = await createPluginServer(
                {},
                { ingestion: false, pluginScheduledTasks: false, processPluginJobs: false }
            )

            expect(startGraphileWorker).not.toHaveBeenCalled()
        })
    })
})
