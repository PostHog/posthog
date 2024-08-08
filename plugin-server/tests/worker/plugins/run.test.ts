import { buildIntegerMatcher } from '../../../src/config/config'
import { Hub, ISOTimestamp, PluginConfig, PluginTaskType, PostIngestionEvent } from '../../../src/types'
import { processError } from '../../../src/utils/db/error'
import { ActionMatcher } from '../../../src/worker/ingestion/action-matcher'
import { runComposeWebhook, runOnEvent, runPluginTask } from '../../../src/worker/plugins/run'

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
                        instance: {
                            getTask,
                        },
                    },
                ],
                [
                    2,
                    {
                        team_id: 2,
                        enabled: false,
                        instance: {
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
                            instance: {
                                getPluginMethod: () => onEvent,
                            },
                        },

                        {
                            plugin_id: 101,
                            team_id: 2,
                            enabled: false,
                            instance: {
                                getPluginMethod: () => onEvent,
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

describe('runComposeWebhook', () => {
    let mockHub: Partial<Hub>,
        composeWebhook: jest.Mock,
        mockPluginConfig: Partial<PluginConfig>,
        mockActionManager: any,
        mockPostgres: any

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
        composeWebhook = jest.fn()
        mockPluginConfig = {
            id: 123,
            plugin_id: 100,
            team_id: 2,
            enabled: false,
            instance: {
                getPluginMethod: () => composeWebhook,
            } as any,
        }
        mockActionManager = {
            getTeamActions: jest.fn(() => ({})),
        }
        mockHub = {
            pluginConfigsPerTeam: new Map([[2, [mockPluginConfig as PluginConfig]]]),
            appMetrics: {
                queueMetric: jest.fn(),
                queueError: jest.fn(),
            } as any,
            actionMatcher: new ActionMatcher(mockPostgres, mockActionManager, {} as any),
        }
    })

    it('calls composeWebhook with PostHogEvent format', async () => {
        await runComposeWebhook(mockHub as Hub, createEvent())

        expect(composeWebhook).toHaveBeenCalledTimes(1)
        expect(composeWebhook.mock.calls[0][0]).toMatchInlineSnapshot(`
            Object {
              "distinct_id": "my_id",
              "event": "$autocapture",
              "properties": Object {},
              "team_id": 2,
              "timestamp": 2020-02-23T02:15:00.000Z,
              "uuid": "uuid1",
            }
        `)
    })

    it('filters in if has matching action', async () => {
        mockPluginConfig.filters = {
            actions: [
                {
                    id: '1',
                    type: 'actions',
                    properties: [],
                    name: '',
                    order: 0,
                },
            ],
        }

        mockActionManager.getTeamActions.mockImplementation(() => ({
            1: {
                steps: [
                    {
                        event: '$autocapture',
                    },
                ],
            },
        }))
        await runComposeWebhook(mockHub as Hub, createEvent())

        expect(composeWebhook).toHaveBeenCalledTimes(1)
    })

    it('filters in if has matching event filter', async () => {
        mockPluginConfig.filters = {
            events: [
                {
                    id: '0',
                    type: 'events',
                    name: '$autocapture',
                    order: 0,
                    properties: [],
                },
            ],
        }

        await runComposeWebhook(mockHub as Hub, createEvent())

        expect(composeWebhook).toHaveBeenCalledTimes(1)
    })

    it('filters in if has matching match action _or_ event filter', async () => {
        mockPluginConfig.filters = {
            events: [
                {
                    type: 'events',
                    name: '$not-autcapture',
                    order: 0,
                    properties: [],
                    id: '0',
                },
            ],
            actions: [
                {
                    id: '1',
                    type: 'actions',
                    properties: [],
                    name: '',
                    order: 0,
                },
            ],
        }

        mockActionManager.getTeamActions.mockImplementation(() => ({
            1: {
                steps: [
                    {
                        event: '$autocapture',
                    },
                ],
            },
        }))

        await runComposeWebhook(mockHub as Hub, createEvent())

        expect(composeWebhook).toHaveBeenCalledTimes(1)
    })

    it('filters out if has matching action that cannot be found', async () => {
        mockPluginConfig.filters = {
            actions: [
                {
                    id: '1',
                    type: 'actions',
                    properties: [],
                    name: '',
                    order: 0,
                },
            ],
        }
        await runComposeWebhook(mockHub as Hub, createEvent())

        expect(composeWebhook).toHaveBeenCalledTimes(0)
    })

    it('filters out if has non-matching action and event filter', async () => {
        mockPluginConfig.filters = {
            events: [
                {
                    type: 'events',
                    name: '$not-autcapture',
                    order: 0,
                    properties: [],
                    id: '0',
                },
            ],
            actions: [
                {
                    id: '1',
                    type: 'actions',
                    properties: [],
                    name: '',
                    order: 0,
                },
            ],
        }

        mockActionManager.getTeamActions.mockImplementation(() => ({
            1: {
                steps: [
                    {
                        event: '$also-not-autocapture',
                    },
                ],
            },
        }))

        await runComposeWebhook(mockHub as Hub, createEvent())

        expect(composeWebhook).toHaveBeenCalledTimes(0)
    })

    it('handles malformed filters and does logs an error', async () => {
        mockPluginConfig.filters = {
            events: {},
        } as any

        await runComposeWebhook(mockHub as Hub, createEvent())

        expect(composeWebhook).toHaveBeenCalledTimes(0)
        expect(mockHub.appMetrics?.queueError).toHaveBeenCalledTimes(1)
        expect(mockHub.appMetrics?.queueError).toHaveBeenLastCalledWith(
            {
                category: 'composeWebhook',
                failures: 1,
                pluginConfigId: 123,
                teamId: 2,
            },
            {
                error: 'Error occurred when processing filters: TypeError: (filters.events || []) is not iterable',
                event: expect.objectContaining({
                    event: '$autocapture',
                }),
            }
        )
    })
})
