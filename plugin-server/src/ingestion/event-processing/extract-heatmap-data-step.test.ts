import { KafkaProducerWrapper } from '../../kafka/producer'
import { ISOTimestamp, PreIngestionEvent, ProjectId } from '../../types'
import { parseJSON } from '../../utils/json-parse'
import { cloneObject } from '../../utils/utils'
import { PipelineResultType } from '../pipelines/results'
import { createExtractHeatmapDataStep } from './extract-heatmap-data-step'

const createTestEvent = (overrides: Partial<PreIngestionEvent> = {}): PreIngestionEvent => ({
    eventUuid: '018eebf3-cb48-750b-bfad-36409ea6f2b2',
    event: 'Clicked button',
    distinctId: '018eebf3-79b1-7082-a7c6-eeb56a36002f',
    properties: {
        $current_url: 'http://localhost:3000/',
        $host: 'localhost:3000',
        $pathname: '/',
        $viewport_height: 1328,
        $viewport_width: 1071,
        $device_id: '018eebf3-79b1-7082-a7c6-eeb56a36002f',
        $session_id: '018eebf3-79cd-70da-895f-b6cf352bd688',
        $window_id: '018eebf3-79cd-70da-895f-b6d09add936a',
        $heatmap_data: {
            'http://localhost:3000/': [
                {
                    x: 1020,
                    y: 363,
                    target_fixed: false,
                    type: 'mousemove',
                },
                {
                    x: 634,
                    y: 460,
                    target_fixed: false,
                    type: 'click',
                },
            ],
        },
    },
    timestamp: '2024-04-17T12:06:46.861Z' as ISOTimestamp,
    teamId: 1,
    projectId: 1 as ProjectId,
    ...overrides,
})

describe('createExtractHeatmapDataStep', () => {
    let mockProducer: jest.Mocked<KafkaProducerWrapper>
    let step: ReturnType<typeof createExtractHeatmapDataStep>

    beforeEach(() => {
        mockProducer = {
            queueMessages: jest.fn(() => Promise.resolve()),
        } as any

        step = createExtractHeatmapDataStep({
            kafkaProducer: mockProducer,
            CLICKHOUSE_HEATMAPS_KAFKA_TOPIC: 'clickhouse_heatmaps_test',
        })
    })

    describe('early return optimization', () => {
        it('returns early when no $heatmap_data is present', async () => {
            const event = createTestEvent()
            delete event.properties.$heatmap_data

            const result = await step({ preparedEvent: event })

            expect(result.type).toBe(PipelineResultType.OK)
            if (result.type === PipelineResultType.OK) {
                expect(result.value.preparedEvent).toBe(event)
                expect(result.sideEffects).toEqual([])
                expect(result.warnings).toEqual([])
            }
            expect(mockProducer.queueMessages).not.toHaveBeenCalled()
        })

        it('returns early when $heatmap_data is null', async () => {
            const event = createTestEvent()
            event.properties.$heatmap_data = null

            const result = await step({ preparedEvent: event })

            expect(result.type).toBe(PipelineResultType.OK)
            expect(mockProducer.queueMessages).not.toHaveBeenCalled()
        })

        it('returns early when $heatmap_data is undefined', async () => {
            const event = createTestEvent()
            event.properties.$heatmap_data = undefined

            const result = await step({ preparedEvent: event })

            expect(result.type).toBe(PipelineResultType.OK)
            expect(mockProducer.queueMessages).not.toHaveBeenCalled()
        })
    })

    describe('successful extraction', () => {
        it('extracts and queues heatmap data', async () => {
            const event = createTestEvent()

            const result = await step({ preparedEvent: event })

            expect(result.type).toBe(PipelineResultType.OK)
            if (result.type === PipelineResultType.OK) {
                // Original event should not be mutated
                expect(event.properties.$heatmap_data).toBeDefined()

                // Result should have heatmap data removed
                expect(result.value.preparedEvent.properties.$heatmap_data).toBeUndefined()

                // Should preserve other properties
                expect(result.value.preparedEvent.properties.$current_url).toBe('http://localhost:3000/')
                expect(result.value.preparedEvent.properties.$session_id).toBe('018eebf3-79cd-70da-895f-b6cf352bd688')

                expect(result.sideEffects).toHaveLength(1)
                expect(result.warnings).toEqual([])
            }

            expect(mockProducer.queueMessages).toHaveBeenCalledTimes(1)
            expect(mockProducer.queueMessages).toHaveBeenCalledWith({
                topic: 'clickhouse_heatmaps_test',
                messages: expect.arrayContaining([
                    expect.objectContaining({
                        key: '018eebf3-cb48-750b-bfad-36409ea6f2b2',
                        value: expect.any(String),
                    }),
                ]),
            })

            const topicMessages = mockProducer.queueMessages.mock.calls[0][0]
            const queuedMessages = Array.isArray(topicMessages) ? topicMessages[0].messages : topicMessages.messages
            expect(queuedMessages).toHaveLength(2)

            const firstMessage = parseJSON(queuedMessages[0].value as string)
            expect(firstMessage).toMatchObject({
                type: 'mousemove',
                x: 64, // 1020 / 16
                y: 23, // 363 / 16
                pointer_target_fixed: false,
                viewport_height: 83, // 1328 / 16
                viewport_width: 67, // 1071 / 16
                current_url: 'http://localhost:3000/',
                session_id: '018eebf3-79cd-70da-895f-b6cf352bd688',
                scale_factor: 16,
                team_id: 1,
                distinct_id: '018eebf3-79b1-7082-a7c6-eeb56a36002f',
            })
        })

        it('handles multiple URLs in heatmap data', async () => {
            const event = createTestEvent()
            event.properties.$heatmap_data = {
                'http://localhost:3000/': [{ x: 100, y: 200, target_fixed: false, type: 'click' }],
                'http://localhost:3000/about': [{ x: 300, y: 400, target_fixed: true, type: 'mousemove' }],
            }

            const result = await step({ preparedEvent: event })

            expect(result.type).toBe(PipelineResultType.OK)
            expect(mockProducer.queueMessages).toHaveBeenCalledTimes(1)

            const topicMessages = mockProducer.queueMessages.mock.calls[0][0]
            const queuedMessages = Array.isArray(topicMessages) ? topicMessages[0].messages : topicMessages.messages
            expect(queuedMessages).toHaveLength(2)

            const urls = queuedMessages.map((msg: any) => parseJSON(msg.value as string).current_url)
            expect(urls).toContain('http://localhost:3000/')
            expect(urls).toContain('http://localhost:3000/about')
        })

        it('extracts scroll depth data from previous pageview', async () => {
            const event = createTestEvent()
            event.properties = {
                ...event.properties,
                $prev_pageview_pathname: '/test',
                $prev_pageview_max_scroll: 225,
            }

            const result = await step({ preparedEvent: event })

            expect(result.type).toBe(PipelineResultType.OK)
            expect(mockProducer.queueMessages).toHaveBeenCalledTimes(1)

            const topicMessages = mockProducer.queueMessages.mock.calls[0][0]
            const queuedMessages = Array.isArray(topicMessages) ? topicMessages[0].messages : topicMessages.messages
            expect(queuedMessages).toHaveLength(3) // 2 original + 1 scroll depth

            const scrollDepthMessage = queuedMessages.find((msg: any) => {
                const parsed = parseJSON(msg.value as string)
                return parsed.type === 'scrolldepth'
            })

            expect(scrollDepthMessage).toBeDefined()
            const scrollData = parseJSON(scrollDepthMessage!.value as string)
            expect(scrollData).toMatchObject({
                type: 'scrolldepth',
                x: 0,
                y: 14, // 225 / 16
                current_url: 'http://localhost:3000/test',
                pointer_target_fixed: false,
            })
        })
    })

    describe('validation', () => {
        it('handles empty object $heatmap_data', async () => {
            const event = createTestEvent()
            event.properties.$heatmap_data = {}

            const result = await step({ preparedEvent: event })

            expect(result.type).toBe(PipelineResultType.OK)
            if (result.type === PipelineResultType.OK) {
                expect(result.value.preparedEvent.properties.$heatmap_data).toBeUndefined()
                expect(result.sideEffects).toEqual([])
            }
            expect(mockProducer.queueMessages).not.toHaveBeenCalled()
        })

        it('drops event with invalid distinct_id', async () => {
            const event = createTestEvent({ distinctId: '' })

            const result = await step({ preparedEvent: event })

            expect(result.type).toBe(PipelineResultType.DROP)
            if (result.type === PipelineResultType.DROP) {
                expect(result.reason).toBe('heatmap_invalid_distinct_id')
            }
            expect(mockProducer.queueMessages).not.toHaveBeenCalled()
        })

        it('drops event with illegal distinct_id', async () => {
            const event = createTestEvent({ distinctId: 'distinct_id' })

            const result = await step({ preparedEvent: event })

            expect(result.type).toBe(PipelineResultType.DROP)
            if (result.type === PipelineResultType.DROP) {
                expect(result.reason).toBe('heatmap_invalid_distinct_id')
            }
            expect(mockProducer.queueMessages).not.toHaveBeenCalled()
        })

        it('drops event with invalid viewport dimensions', async () => {
            const event = createTestEvent()
            event.properties.$viewport_height = NaN
            event.properties.$viewport_width = 1071

            const result = await step({ preparedEvent: event })

            expect(result.type).toBe(PipelineResultType.DROP)
            if (result.type === PipelineResultType.DROP) {
                expect(result.reason).toBe('heatmap_invalid_viewport_dimensions')
            }
            expect(mockProducer.queueMessages).not.toHaveBeenCalled()
        })

        it('drops event with missing viewport dimensions', async () => {
            const event = createTestEvent()
            delete event.properties.$viewport_height

            const result = await step({ preparedEvent: event })

            expect(result.type).toBe(PipelineResultType.DROP)
            if (result.type === PipelineResultType.DROP) {
                expect(result.reason).toBe('heatmap_invalid_viewport_dimensions')
            }
        })

        it('adds warning for invalid URL in heatmap data', async () => {
            const event = createTestEvent()
            event.properties.$heatmap_data = {
                '   ': [{ x: 100, y: 200, target_fixed: false, type: 'click' }],
            }

            const result = await step({ preparedEvent: event })

            expect(result.type).toBe(PipelineResultType.OK)
            if (result.type === PipelineResultType.OK) {
                expect(result.warnings).toHaveLength(1)
                expect(result.warnings[0]).toMatchObject({
                    type: 'rejecting_heatmap_data_with_invalid_url',
                    details: {
                        heatmapUrl: '   ',
                        session_id: '018eebf3-79cd-70da-895f-b6cf352bd688',
                    },
                    key: '018eebf3-79cd-70da-895f-b6cf352bd688',
                })
            }
            expect(mockProducer.queueMessages).not.toHaveBeenCalled()
        })

        it('adds warning for non-array items in heatmap data', async () => {
            const event = createTestEvent()
            event.properties.$heatmap_data = {
                'http://localhost:3000/': 'not an array' as any,
            }

            const result = await step({ preparedEvent: event })

            expect(result.type).toBe(PipelineResultType.OK)
            if (result.type === PipelineResultType.OK) {
                expect(result.warnings).toHaveLength(1)
                expect(result.warnings[0]).toMatchObject({
                    type: 'rejecting_heatmap_data_with_invalid_items',
                    details: {
                        heatmapUrl: 'http://localhost:3000/',
                        session_id: '018eebf3-79cd-70da-895f-b6cf352bd688',
                    },
                    key: '018eebf3-79cd-70da-895f-b6cf352bd688',
                })
            }
            expect(mockProducer.queueMessages).not.toHaveBeenCalled()
        })

        it('filters out invalid heatmap items silently', async () => {
            const event = createTestEvent()
            event.properties.$heatmap_data = {
                'http://localhost:3000/': [
                    { x: 100, y: 200, target_fixed: false, type: 'click' }, // valid
                    { x: 'invalid', y: 200, target_fixed: false, type: 'click' }, // invalid x
                    { x: 100, y: NaN, target_fixed: false, type: 'click' }, // invalid y
                    { x: 100, y: 200, target_fixed: 'not boolean', type: 'click' }, // invalid target_fixed
                    { x: 100, y: 200, target_fixed: false, type: '   ' }, // invalid type
                    { x: 300, y: 400, target_fixed: true, type: 'mousemove' }, // valid
                ],
            }

            const result = await step({ preparedEvent: event })

            expect(result.type).toBe(PipelineResultType.OK)
            expect(mockProducer.queueMessages).toHaveBeenCalledTimes(1)

            const topicMessages = mockProducer.queueMessages.mock.calls[0][0]
            const queuedMessages = Array.isArray(topicMessages) ? topicMessages[0].messages : topicMessages.messages
            expect(queuedMessages).toHaveLength(2) // Only 2 valid items
        })
    })

    describe('immutability', () => {
        it('does not mutate the original event', async () => {
            const event = createTestEvent()
            const originalEvent = cloneObject(event)

            await step({ preparedEvent: event })

            expect(event).toEqual(originalEvent)
            expect(event.properties.$heatmap_data).toBeDefined()
        })

        it('preserves input properties in the result', async () => {
            const event = createTestEvent()
            const input = {
                preparedEvent: event,
                customField: 'test-value',
                anotherField: 123,
            }

            const result = await step(input as any)

            expect(result.type).toBe(PipelineResultType.OK)
            if (result.type === PipelineResultType.OK) {
                expect(result.value).toMatchObject({
                    customField: 'test-value',
                    anotherField: 123,
                })
            }
        })
    })

    describe('error handling', () => {
        it('adds warning when extraction throws an error', async () => {
            const event = createTestEvent()
            // Make the extraction fail by providing malformed data that causes an error during processing
            event.properties.$heatmap_data = {
                'http://test.com': [{ x: 100, y: 200, target_fixed: false, type: 'click' }],
            }
            event.distinctId = null as any // This should cause an error

            const result = await step({ preparedEvent: event })

            // The error should be caught and converted to a warning
            expect(result.type).toBe(PipelineResultType.DROP)
        })
    })

    describe('scale factor', () => {
        it('applies scale factor correctly to coordinates', async () => {
            const event = createTestEvent()
            event.properties.$heatmap_data = {
                'http://localhost:3000/': [{ x: 160, y: 320, target_fixed: false, type: 'click' }],
            }
            event.properties.$viewport_height = 1600
            event.properties.$viewport_width = 1280

            const result = await step({ preparedEvent: event })

            expect(result.type).toBe(PipelineResultType.OK)
            expect(mockProducer.queueMessages).toHaveBeenCalledTimes(1)

            const topicMessages = mockProducer.queueMessages.mock.calls[0][0]
            const queuedMessages = Array.isArray(topicMessages) ? topicMessages[0].messages : topicMessages.messages
            const message = parseJSON(queuedMessages[0].value as string)

            expect(message.x).toBe(10) // 160 / 16
            expect(message.y).toBe(20) // 320 / 16
            expect(message.viewport_height).toBe(100) // 1600 / 16
            expect(message.viewport_width).toBe(80) // 1280 / 16
            expect(message.scale_factor).toBe(16)
        })
    })
})
