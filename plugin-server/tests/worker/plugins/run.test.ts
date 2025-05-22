import { buildIntegerMatcher } from '../../../src/config/config'
import { Hub, ISOTimestamp, PluginConfig, PostIngestionEvent } from '../../../src/types'
import { ActionMatcher } from '../../../src/worker/ingestion/action-matcher'
import { runComposeWebhook, runOnEvent } from '../../../src/worker/plugins/run'

jest.mock('../../../src/utils/logger')
jest.mock('../../../src/utils/db/error')

describe('runOnEvent', () => {
    let mockHub: any, onEvent: jest.Mock

    // @ts-expect-error TODO: Fix type error
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
        const result = await runOnEvent(mockHub, createEvent())
        await Promise.all(result.map((r) => r.backgroundTask))

        expect(onEvent).toHaveBeenCalledTimes(2)
        expect(onEvent.mock.calls[0][0]).toMatchInlineSnapshot(`
            {
              "$set": undefined,
              "$set_once": undefined,
              "distinct_id": "my_id",
              "elements": [],
              "event": "$autocapture",
              "ip": null,
              "properties": {},
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
        const result = await runOnEvent(mockHub, mockEvent)
        await Promise.all(result.map((r) => r.backgroundTask))

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
        const result = await runOnEvent(mockHub, mockEvent)
        await Promise.all(result.map((r) => r.backgroundTask))

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

    // @ts-expect-error TODO: Fix type error
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
            actionMatcher: new ActionMatcher(mockPostgres, mockActionManager),
        }
    })

    it('calls composeWebhook with PostHogEvent format', async () => {
        await runComposeWebhook(mockHub as Hub, createEvent())

        expect(composeWebhook).toHaveBeenCalledTimes(1)
        expect(composeWebhook.mock.calls[0][0]).toMatchInlineSnapshot(`
            {
              "distinct_id": "my_id",
              "event": "$autocapture",
              "properties": {},
              "team_id": 2,
              "timestamp": 2020-02-23T02:15:00.000Z,
              "uuid": "uuid1",
            }
        `)
    })
})
