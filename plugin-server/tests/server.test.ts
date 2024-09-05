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

    function createPluginServer(config: Partial<PluginsServerConfig>, capabilities: PluginServerCapabilities) {
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

    // Running all capabilities together takes too long in tests, so they are split up
    test('startPluginsServer does not error - ingestion', async () => {
        const testCode = `
        async function processEvent (event) {
            return event
        }
    `
        await resetTestDatabase(testCode)
        pluginsServer = await createPluginServer(
            {},
            {
                http: true,
                mmdb: true,
                ingestion: true,
                ingestionOverflow: true,
                ingestionHistorical: true,
                appManagementSingleton: true,
                preflightSchedules: true,
                syncInlinePlugins: true,
            }
        )
    })
    test('startPluginsServer does not error - pipelines', async () => {
        const testCode = `
        async function processEvent (event) {
            return event
        }
    `
        await resetTestDatabase(testCode)
        pluginsServer = await createPluginServer(
            {},
            {
                http: true,
                eventsIngestionPipelines: true,
                syncInlinePlugins: true,
            }
        )
    })

    test('startPluginsServer does not error - cdp', async () => {
        const testCode = `
        async function processEvent (event) {
            return event
        }
    `
        await resetTestDatabase(testCode)
        pluginsServer = await createPluginServer(
            {},
            {
                http: true,
                pluginScheduledTasks: true,
                processPluginJobs: true,
                processAsyncOnEventHandlers: true,
                processAsyncWebhooksHandlers: true,
                cdpProcessedEvents: true,
                cdpFunctionCallbacks: true,
                cdpCyclotronWorker: true,
                syncInlinePlugins: true,
            }
        )
    })

    test('startPluginsServer does not error - replay', async () => {
        const testCode = `
        async function processEvent (event) {
            return event
        }
    `
        await resetTestDatabase(testCode)
        pluginsServer = await createPluginServer(
            {},
            {
                http: true,
                sessionRecordingBlobIngestion: true,
                sessionRecordingBlobOverflowIngestion: true,
                syncInlinePlugins: true,
            }
        )
    })

    test('starting and stopping node-schedule scheduled jobs', async () => {
        expect(numberOfScheduledJobs()).toEqual(0)

        pluginsServer = await createPluginServer(
            {},
            {
                http: true,
                pluginScheduledTasks: true,
                processAsyncWebhooksHandlers: true,
                preflightSchedules: true,
                syncInlinePlugins: true,
            }
        )

        expect(numberOfScheduledJobs()).toBeGreaterThan(1)

        await pluginsServer.stop?.()
        pluginsServer = null

        expect(numberOfScheduledJobs()).toEqual(0)
    })

    describe('plugin-server capabilities', () => {
        test('starts graphile for scheduled tasks capability', async () => {
            pluginsServer = await createPluginServer(
                {},
                { ingestion: true, pluginScheduledTasks: true, processPluginJobs: true, syncInlinePlugins: true }
            )

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
