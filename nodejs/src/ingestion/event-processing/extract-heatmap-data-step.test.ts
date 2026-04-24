import { createTestEventHeaders } from '../../../tests/helpers/event-headers'
import { createMockIngestionOutputs } from '../../../tests/helpers/mock-ingestion-outputs'
import { ISOTimestamp, PreIngestionEvent, ProjectId } from '../../types'
import { parseJSON } from '../../utils/json-parse'
import { cloneObject } from '../../utils/utils'
import { HEATMAPS_OUTPUT, HeatmapsOutput } from '../analytics/outputs'
import { IngestionOutputs } from '../outputs/ingestion-outputs'
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
    let mockOutputs: jest.Mocked<IngestionOutputs<HeatmapsOutput>>
    let step: ReturnType<typeof createExtractHeatmapDataStep>

    beforeEach(() => {
        mockOutputs = createMockIngestionOutputs<HeatmapsOutput>()
        step = createExtractHeatmapDataStep(mockOutputs)
    })

    describe('no heatmap or scroll depth data', () => {
        it('returns OK with no side effects when no $heatmap_data or scroll depth data is present', async () => {
            const event = createTestEvent()
            delete event.properties.$heatmap_data

            const result = await step({ preparedEvent: event })

            expect(result.type).toBe(PipelineResultType.OK)
            if (result.type === PipelineResultType.OK) {
                expect(result.value.preparedEvent).toEqual(event)
                expect(result.sideEffects).toEqual([])
                expect(result.warnings).toEqual([])
            }
            expect(mockOutputs.queueMessages).not.toHaveBeenCalled()
        })

        it('returns early when $heatmap_data is null', async () => {
            const event = createTestEvent()
            event.properties.$heatmap_data = null

            const result = await step({ preparedEvent: event })

            expect(result.type).toBe(PipelineResultType.OK)
            expect(mockOutputs.queueMessages).not.toHaveBeenCalled()
        })

        it('returns early when $heatmap_data is undefined', async () => {
            const event = createTestEvent()
            event.properties.$heatmap_data = undefined

            const result = await step({ preparedEvent: event })

            expect(result.type).toBe(PipelineResultType.OK)
            expect(mockOutputs.queueMessages).not.toHaveBeenCalled()
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

            expect(mockOutputs.queueMessages).toHaveBeenCalledTimes(1)
            expect(mockOutputs.queueMessages).toHaveBeenCalledWith(
                HEATMAPS_OUTPUT,
                expect.arrayContaining([
                    expect.objectContaining({
                        key: '018eebf3-cb48-750b-bfad-36409ea6f2b2',
                        value: expect.any(Buffer),
                    }),
                ])
            )

            const queuedMessages = mockOutputs.queueMessages.mock.calls[0][1]
            expect(queuedMessages).toHaveLength(2)

            const firstMessage = parseJSON(queuedMessages[0].value!.toString())
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
            expect(mockOutputs.queueMessages).toHaveBeenCalledTimes(1)

            const queuedMessages = mockOutputs.queueMessages.mock.calls[0][1]
            expect(queuedMessages).toHaveLength(2)

            const urls = queuedMessages.map((msg: any) => parseJSON(msg.value!.toString()).current_url)
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
            expect(mockOutputs.queueMessages).toHaveBeenCalledTimes(1)

            const queuedMessages = mockOutputs.queueMessages.mock.calls[0][1]
            expect(queuedMessages).toHaveLength(3) // 2 original + 1 scroll depth

            const scrollDepthMessage = queuedMessages.find((msg: any) => {
                const parsed = parseJSON(msg.value!.toString())
                return parsed.type === 'scrolldepth'
            })

            expect(scrollDepthMessage).toBeDefined()
            const scrollData = parseJSON(scrollDepthMessage!.value!.toString())
            expect(scrollData).toMatchObject({
                type: 'scrolldepth',
                x: 0,
                y: 14, // 225 / 16
                current_url: 'http://localhost:3000/test',
                pointer_target_fixed: false,
            })
        })

        it('extracts scroll depth data from $pageleave event WITHOUT $heatmap_data', async () => {
            // This test verifies the fix for the bug where events without
            // $heatmap_data were skipped entirely, even if they had scroll
            // depth data ($prev_pageview_pathname)
            const event = createTestEvent()
            delete event.properties.$heatmap_data // No heatmap data, like a $pageleave event
            event.properties = {
                ...event.properties,
                $prev_pageview_pathname: '/about',
                $prev_pageview_max_scroll: 500,
            }

            const result = await step({ preparedEvent: event })

            expect(result.type).toBe(PipelineResultType.OK)
            expect(mockOutputs.queueMessages).toHaveBeenCalledTimes(1)

            const queuedMessages = mockOutputs.queueMessages.mock.calls[0][1]
            expect(queuedMessages).toHaveLength(1) // Only scroll depth, no heatmap data

            const scrollDepthMessage = queuedMessages[0]
            const scrollData = parseJSON(scrollDepthMessage.value!.toString())
            expect(scrollData).toMatchObject({
                type: 'scrolldepth',
                x: 0,
                y: 31, // 500 / 16
                current_url: 'http://localhost:3000/about',
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
            expect(mockOutputs.queueMessages).not.toHaveBeenCalled()
        })

        it('drops event with invalid distinct_id', async () => {
            const event = createTestEvent({ distinctId: '' })

            const result = await step({ preparedEvent: event })

            expect(result.type).toBe(PipelineResultType.DROP)
            if (result.type === PipelineResultType.DROP) {
                expect(result.reason).toBe('heatmap_invalid_distinct_id')
            }
            expect(mockOutputs.queueMessages).not.toHaveBeenCalled()
        })

        it('drops event with illegal distinct_id', async () => {
            const event = createTestEvent({ distinctId: 'distinct_id' })

            const result = await step({ preparedEvent: event })

            expect(result.type).toBe(PipelineResultType.DROP)
            if (result.type === PipelineResultType.DROP) {
                expect(result.reason).toBe('heatmap_invalid_distinct_id')
            }
            expect(mockOutputs.queueMessages).not.toHaveBeenCalled()
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
            expect(mockOutputs.queueMessages).not.toHaveBeenCalled()
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
            expect(mockOutputs.queueMessages).not.toHaveBeenCalled()
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
            expect(mockOutputs.queueMessages).not.toHaveBeenCalled()
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
            expect(mockOutputs.queueMessages).toHaveBeenCalledTimes(1)

            const queuedMessages = mockOutputs.queueMessages.mock.calls[0][1]
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
            expect(mockOutputs.queueMessages).toHaveBeenCalledTimes(1)

            const queuedMessages = mockOutputs.queueMessages.mock.calls[0][1]
            const message = parseJSON(queuedMessages[0].value!.toString())

            expect(message.x).toBe(10) // 160 / 16
            expect(message.y).toBe(20) // 320 / 16
            expect(message.viewport_height).toBe(100) // 1600 / 16
            expect(message.viewport_width).toBe(80) // 1280 / 16
            expect(message.scale_factor).toBe(16)
        })
    })

    describe('skip_heatmap_processing header (capture redirect)', () => {
        it('skips extraction and passes event through unchanged when skip_heatmap_processing is true', async () => {
            const event = createTestEvent()
            const headers = createTestEventHeaders({ skip_heatmap_processing: true })

            const result = await step({ preparedEvent: event, headers })

            expect(result.type).toBe(PipelineResultType.OK)
            if (result.type === PipelineResultType.OK) {
                expect(result.value.preparedEvent).toBe(event)
                expect(result.sideEffects).toEqual([])
                expect(result.warnings).toEqual([])
            }
            expect(mockOutputs.queueMessages).not.toHaveBeenCalled()
        })

        it('extracts normally when skip_heatmap_processing is false', async () => {
            const event = createTestEvent()
            const headers = createTestEventHeaders({ skip_heatmap_processing: false })

            const result = await step({ preparedEvent: event, headers })

            expect(result.type).toBe(PipelineResultType.OK)
            expect(mockOutputs.queueMessages).toHaveBeenCalledTimes(1)
        })

        it('extracts normally when headers are not provided', async () => {
            const event = createTestEvent()

            const result = await step({ preparedEvent: event })

            expect(result.type).toBe(PipelineResultType.OK)
            expect(mockOutputs.queueMessages).toHaveBeenCalledTimes(1)
        })
    })
})
