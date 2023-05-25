import assert from 'assert'

import { PluginConfig, PluginTaskType } from '../../../src/types'
import { processError } from '../../../src/utils/db/error'
import { loadPluginConfig, runPluginTask } from '../../../src/worker/plugins/run'

jest.mock('../../../src/utils/status')
jest.mock('../../../src/utils/db/error')

describe('runPluginTask()', () => {
    let mockHub: any, exec: any, getTask: any

    beforeEach(() => {
        exec = jest.fn()
        getTask = jest.fn()
        mockHub = {
            pluginConfigSecretLookup: new Map([]),
            pluginConfigSecrets: new Map([]),
            pluginConfigs: new Map([
                [
                    1,
                    {
                        team_id: 2,
                        vm: {
                            getTask,
                        },
                    },
                ],
            ]),
            appMetrics: {
                queueMetric: jest.fn(),
                queueError: jest.fn(),
            },
            db: {
                postgresQuery: jest.fn(),
                queuePluginLogEntry: jest.fn(),
            },
        }
    })

    it('calls tracked task and queues metric for scheduled task', async () => {
        getTask.mockResolvedValue({ exec })

        await runPluginTask(mockHub, 'some_task', PluginTaskType.Schedule, 1, { foo: 1 })

        expect(exec).toHaveBeenCalledWith({ foo: 1 })
        expect(mockHub.appMetrics.queueMetric).toHaveBeenCalledWith({
            category: 'scheduledTask',
            pluginConfigId: 1,
            teamId: 2,
            successes: 1,
        })
    })

    it('calls tracked task for job', async () => {
        getTask.mockResolvedValue({ exec })

        await runPluginTask(mockHub, 'some_task', PluginTaskType.Job, 1)

        expect(exec).toHaveBeenCalled()
        expect(mockHub.appMetrics.queueMetric).not.toHaveBeenCalled()
    })

    it('does not queue metric for ignored scheduled task', async () => {
        getTask.mockResolvedValue({ exec, __ignoreForAppMetrics: true })

        await runPluginTask(mockHub, 'some_task', PluginTaskType.Schedule, 1, { foo: 1 })

        expect(exec).toHaveBeenCalledWith({ foo: 1 })
        expect(mockHub.appMetrics.queueMetric).not.toHaveBeenCalled()
    })

    it('tracks error if scheduled task failed', async () => {
        getTask.mockResolvedValue({ exec })
        exec.mockRejectedValue(new Error('Some error'))

        await runPluginTask(mockHub, 'some_task', PluginTaskType.Schedule, 1)

        expect(exec).toHaveBeenCalled()
        expect(mockHub.appMetrics.queueMetric).not.toHaveBeenCalled()
        expect(mockHub.appMetrics.queueError).toHaveBeenCalledWith(
            {
                category: 'scheduledTask',
                pluginConfigId: 1,
                teamId: 2,
                failures: 1,
            },
            { error: new Error('Some error') }
        )
    })

    it('calls processError if task not found', async () => {
        await runPluginTask(mockHub, 'some_task', PluginTaskType.Schedule, -1)

        expect(processError).toHaveBeenCalledWith(
            mockHub,
            null,
            new Error('Task "some_task" not found for plugin "undefined" with config id -1')
        )
        expect(mockHub.appMetrics.queueError).not.toHaveBeenCalled()
    })

    it('starts a usage VM given a pluginConfig', async () => {
        const pluginConfig: PluginConfig = {
            id: 1,
            team_id: 1,
            plugin_id: 1,
            enabled: true,
            order: 0,
            config: {},
            has_error: false,
            created_at: '2021-01-01',
            /** Cached source for plugin.json from a joined PluginSourceFile query */
            plugin: {
                id: 1,
                organization_id: '1',
                name: 'Test Plugin',
                description: 'Test Plugin',
                is_global: true,
                plugin_type: 'source',
                /** Cached source for plugin.json from a joined PluginSourceFile query */
                /** Cached source for index.ts from a joined PluginSourceFile query */
                source__index_ts: `
                    export async function processEvent(event) {
                        event.properties.processed = 'hell yes'
                        event.properties.upperUuid = event.properties.uuid?.toUpperCase()
                        event.properties['$snapshot_data'] = 'no way'
                        event.properties.runCount = (event.properties.runCount || 0) + 1
                        return event
                    }
                `,
                /** Cached source for frontend.tsx from a joined PluginSourceFile query */
                /** Cached source for site.ts from a joined PluginSourceFile query */
                from_json: false,
                from_web: false,
                is_stateless: false,
                capabilities: { methods: ['processEvent'] },
            },
        }
        await loadPluginConfig(mockHub, pluginConfig)
        assert(pluginConfig.vm)
        const processEvent = await pluginConfig.vm.getVmMethod('processEvent')
        assert(processEvent)
        await processEvent({
            properties: { uuid: '123' },
            event: 'some_event',
            team_id: 1,
            distinct_id: '123',
            ip: '',
            site_url: '',
            uuid: '123',
            now: new Date().toISOString(),
        })
    })
})
