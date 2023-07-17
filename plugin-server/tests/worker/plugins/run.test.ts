import { PluginTaskType } from '../../../src/types'
import { processError } from '../../../src/utils/db/error'
import { runPluginTask } from '../../../src/worker/plugins/run'

jest.mock('../../../src/utils/status')
jest.mock('../../../src/utils/db/error')

describe('runPluginTask()', () => {
    let mockHub: any, exec: any, getTask: any

    beforeEach(() => {
        exec = jest.fn()
        getTask = jest.fn()
        mockHub = {
            pluginConfigs: new Map([
                [
                    1,
                    {
                        team_id: 2,
                        enabled: true,
                        vm: {
                            getTask,
                        },
                    },
                ],
                [
                    2,
                    {
                        team_id: 2,
                        enabled: false,
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

    it('skips the task if the pluginconfig is disabled', async () => {
        await runPluginTask(mockHub, 'some_task', PluginTaskType.Schedule, 2)

        expect(processError).not.toHaveBeenCalledWith()
        expect(exec).not.toHaveBeenCalled()
        expect(mockHub.appMetrics.queueMetric).not.toHaveBeenCalled()
    })
})
