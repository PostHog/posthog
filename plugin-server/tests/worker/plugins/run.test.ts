import { buildIntegerMatcher } from '../../../src/config/config'
import { ISOTimestamp, PluginTaskType, PostIngestionEvent } from '../../../src/types'
import { processError } from '../../../src/utils/db/error'
import { runOnEvent, runPluginTask } from '../../../src/worker/plugins/run'

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

describe('runOnEvent', () => {
    let mockHub: any, onEvent: jest.Mock

    const createEvent = (data: Partial<PostIngestionEvent> = {}): PostIngestionEvent => ({
        eventUuid: 'uuid1',
        distinctId: 'my_id',
        teamId: 2,
        timestamp: '2020-02-23T02:15:00.000Z' as ISOTimestamp,
        event: '$autocapture',
        properties: {},
        elementsList: undefined,
        person_id: 'F99FA0A1-E0C2-4CFE-A09A-4C3C4327A4CC',
        person_created_at: '2020-02-20T02:15:00.000Z' as ISOTimestamp,
        person_properties: {},
        ...data,
    })

    beforeEach(() => {
        onEvent = jest.fn()
        mockHub = {
            pluginConfigsPerTeam: new Map([
                [
                    2,
                    [
                        {
                            plugin_id: 100,
                            team_id: 2,
                            enabled: false,
                            vm: {
                                getVmMethod: () => onEvent,
                            },
                        },

                        {
                            plugin_id: 101,
                            team_id: 2,
                            enabled: false,
                            vm: {
                                getVmMethod: () => onEvent,
                            },
                        },
                    ],
                ],
            ]),
            appMetrics: {
                queueMetric: jest.fn(),
                queueError: jest.fn(),
            },
        }
    })

    it('calls onEvent', async () => {
        await runOnEvent(mockHub, createEvent())

        expect(onEvent).toHaveBeenCalledTimes(2)
        expect(onEvent.mock.calls[0][0]).toMatchInlineSnapshot(`
            Object {
              "$set": undefined,
              "$set_once": undefined,
              "distinct_id": "my_id",
              "elements": Array [],
              "event": "$autocapture",
              "ip": null,
              "properties": Object {},
              "team_id": 2,
              "timestamp": "2020-02-23T02:15:00.000Z",
              "uuid": "uuid1",
            }
        `)
    })

    it('parses elements when necessary', async () => {
        mockHub.pluginConfigsToSkipElementsParsing = buildIntegerMatcher('100', true)
        const mockEvent = createEvent({
            properties: {
                $elements_chain: 'random',
            },
        })
        await runOnEvent(mockHub, mockEvent)

        expect(onEvent).toHaveBeenCalledTimes(2)

        // First call is without elements
        expect(onEvent.mock.calls[0][0]).toMatchObject({
            elements: [],
        })

        // Second call requires it so it is added
        expect(onEvent.mock.calls[1][0]).toMatchObject({
            elements: [{ attributes: {}, order: 0, tag_name: 'random' }],
        })

        // the event itself is mutated for cachability
        expect(mockEvent.elementsList).toEqual([{ attributes: {}, order: 0, tag_name: 'random' }])
    })

    it('skips elements parsing when not useful', async () => {
        mockHub.pluginConfigsToSkipElementsParsing = buildIntegerMatcher('100,101', true)
        const mockEvent = createEvent({
            properties: {
                $elements_chain: 'random',
            },
        })
        await runOnEvent(mockHub, mockEvent)

        expect(onEvent).toHaveBeenCalledTimes(2)

        // First call is without elements
        expect(onEvent.mock.calls[0][0]).toMatchObject({
            elements: [],
        })

        // Second call requires it so it is added
        expect(onEvent.mock.calls[1][0]).toMatchObject({
            elements: [],
        })

        // the event itself is mutated for cachability
        expect(mockEvent.elementsList).toEqual(undefined)
    })
})
