import { KafkaProducerWrapper, TopicMessage } from '../../../../src/kafka/producer'
import { ISOTimestamp, PreIngestionEvent, ProjectId } from '../../../../src/types'
import { parseJSON } from '../../../../src/utils/json-parse'
import { cloneObject } from '../../../../src/utils/utils'
import { extractHeatmapDataStep } from '../../../../src/worker/ingestion/event-pipeline/extractHeatmapDataStep'
import { EventPipelineRunner } from '../../../../src/worker/ingestion/event-pipeline/runner'

jest.mock('../../../../src/worker/plugins/run')

const preIngestionEvent: PreIngestionEvent = {
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
                {
                    x: 634,
                    y: 460,
                    target_fixed: false,
                    type: 'click',
                },
                {
                    x: 634,
                    y: 460,
                    target_fixed: false,
                    type: 'rageclick',
                },
                {
                    x: 634,
                    y: 460,
                    target_fixed: false,
                    type: 'click',
                },
                {
                    x: 634,
                    y: 460,
                    target_fixed: false,
                    type: 'click',
                },
                {
                    x: 634,
                    y: 460,
                    target_fixed: false,
                    type: 'click',
                },
                {
                    x: 634,
                    y: 460,
                    target_fixed: false,
                    type: 'click',
                },
                {
                    x: 634,
                    y: 460,
                    target_fixed: false,
                    type: 'mousemove',
                },
                {
                    x: 1052,
                    y: 665,
                    target_fixed: false,
                    type: 'mousemove',
                },
                {
                    x: 632,
                    y: 436,
                    target_fixed: false,
                    type: 'click',
                },
                {
                    x: 632,
                    y: 436,
                    target_fixed: false,
                    type: 'click',
                },
                {
                    x: 632,
                    y: 436,
                    target_fixed: false,
                    type: 'rageclick',
                },
                {
                    x: 632,
                    y: 436,
                    target_fixed: false,
                    type: 'click',
                },
                {
                    x: 713,
                    y: 264,
                    target_fixed: false,
                    type: 'click',
                },
                {
                    x: 119,
                    y: 143,
                    target_fixed: false,
                    type: 'click',
                },
            ],
        },
    },
    timestamp: '2024-04-17T12:06:46.861Z' as ISOTimestamp,
    teamId: 1,
    projectId: 1 as ProjectId,
}

describe('extractHeatmapDataStep()', () => {
    let runner: EventPipelineRunner
    let event: PreIngestionEvent
    const mockProducer: jest.Mocked<KafkaProducerWrapper> = {
        queueMessages: jest.fn(() => Promise.resolve()) as any,
    } as any

    beforeEach(() => {
        event = cloneObject(preIngestionEvent)
        runner = {
            hub: {
                kafkaProducer: mockProducer,
                teamManager: {
                    // @ts-expect-error this is a mock, this is all right
                    getTeam: jest.fn(() => Promise.resolve({ heatmaps_opt_in: true })),
                },
            },
        }
    })

    it('parses and ingests correct $heatmap_data', async () => {
        const response = await extractHeatmapDataStep(runner, event)
        expect(response[0]).toEqual(event)
        expect(response[0].properties.$heatmap_data).toBeUndefined()
        expect(response[1]).toHaveLength(1)
        expect(mockProducer.queueMessages).toHaveBeenCalledTimes(1)
        const messages = (mockProducer.queueMessages.mock.calls[0][0] as TopicMessage).messages
        expect(messages).toHaveLength(16)
        const parsed = parseJSON(messages[0].value!.toString())

        expect(parsed).toMatchInlineSnapshot(`
            {
              "current_url": "http://localhost:3000/",
              "distinct_id": "018eebf3-79b1-7082-a7c6-eeb56a36002f",
              "pointer_target_fixed": false,
              "scale_factor": 16,
              "session_id": "018eebf3-79cd-70da-895f-b6cf352bd688",
              "team_id": 1,
              "timestamp": "2024-04-17 12:06:46.861",
              "type": "mousemove",
              "viewport_height": 83,
              "viewport_width": 67,
              "x": 64,
              "y": 23,
            }
        `)

        // The rest we can just compare the buffers
        expect(mockProducer.queueMessages.mock.calls).toMatchSnapshot()
    })

    it('additionally parses ', async () => {
        event.properties = {
            ...event.properties,
            $prev_pageview_pathname: '/test',
            $prev_pageview_max_scroll: 225,
            $prev_pageview_last_content: 1445,
            $prev_pageview_max_content: 1553,
        }

        const response = await extractHeatmapDataStep(runner, event)
        // We do delete heatmap data
        expect(response[0].properties.$heatmap_data).toBeUndefined()
        // We don't delete scroll properties
        expect(response[0].properties.$prev_pageview_max_scroll).toEqual(225)

        expect(mockProducer.queueMessages).toHaveBeenCalledTimes(1)
        const messages = (mockProducer.queueMessages.mock.calls[0][0] as TopicMessage).messages
        expect(messages).toHaveLength(17)

        const allParsedMessages = messages.map((call) => parseJSON(call.value!.toString()))

        expect(allParsedMessages.find((x) => x.type === 'scrolldepth')).toMatchInlineSnapshot(`
            {
              "current_url": "http://localhost:3000/test",
              "distinct_id": "018eebf3-79b1-7082-a7c6-eeb56a36002f",
              "pointer_target_fixed": false,
              "scale_factor": 16,
              "session_id": "018eebf3-79cd-70da-895f-b6cf352bd688",
              "team_id": 1,
              "timestamp": "2024-04-17 12:06:46.861",
              "type": "scrolldepth",
              "viewport_height": 83,
              "viewport_width": 67,
              "x": 0,
              "y": 14,
            }
        `)
    })

    it('drops if the associated team has explicit opt out', async () => {
        // @ts-expect-error this is a mock, this is all right
        runner.hub.teamManager.getTeam = jest.fn(() => Promise.resolve({ heatmaps_opt_in: false }))

        const response = await extractHeatmapDataStep(runner, event)
        expect(response[0]).toEqual(event)
        expect(response[0].properties.$heatmap_data).toBeUndefined()
        expect(response[1]).toHaveLength(0)
        expect(mockProducer.queueMessages).toHaveBeenCalledTimes(0)
    })

    describe('validation', () => {
        it('handles empty array $heatmap_data', async () => {
            event.properties.$heatmap_data = []
            const response = await extractHeatmapDataStep(runner, event)
            expect(response).toEqual([event, []])
            expect(response[0].properties.$heatmap_data).toBeUndefined()
        })

        it('handles empty object $heatmap_data', async () => {
            event.properties.$heatmap_data = {}
            const response = await extractHeatmapDataStep(runner, event)
            expect(response).toEqual([event, []])
            expect(response[0].properties.$heatmap_data).toBeUndefined()
        })

        it('ignores events without $heatmap_data', async () => {
            event.properties.$heatmap_data = null
            const response = await extractHeatmapDataStep(runner, event)
            expect(response).toEqual([event, []])
            expect(response[0].properties.$heatmap_data).toBeUndefined()
        })

        it('ignores events with bad $heatmap_data', async () => {
            event.properties.$heatmap_data = 'wat'
            const response = await extractHeatmapDataStep(runner, event)
            expect(response).toEqual([event, []])
            expect(response[0].properties.$heatmap_data).toBeUndefined()

            expect(runner.hub.kafkaProducer.queueMessages).toHaveBeenCalledTimes(1)
            expect(runner.hub.kafkaProducer.queueMessages).toHaveBeenCalledWith(
                expect.objectContaining({ topic: 'clickhouse_ingestion_warnings_test' })
            )
        })

        it.each([
            [
                {
                    '    ': [
                        {
                            x: 1020,
                            y: 363,
                            target_fixed: 'why would i even be a string?',
                            type: 'mousemove',
                        },
                    ],
                },
            ],
            [
                {
                    '    ': [
                        {
                            x: 1020,
                            y: 363,
                            target_fixed: false,
                            type: 'mousemove',
                        },
                    ],
                },
            ],
            [
                {
                    'x must be a number': [
                        {
                            x: '1020',
                            y: 363,
                            target_fixed: false,
                            type: 'mousemove',
                        },
                    ],
                },
            ],
            [
                {
                    'y must be a number': [
                        {
                            x: 1020,
                            y: '363',
                            target_fixed: false,
                            type: 'mousemove',
                        },
                    ],
                },
            ],
            [
                {
                    'type must be present': [
                        {
                            x: 1020,
                            y: 363,
                            target_fixed: false,
                            type: '     ',
                        },
                    ],
                },
            ],
        ])('only includes valid heatmap data', async (invalidEvent) => {
            event.properties.$heatmap_data = invalidEvent
            const response = await extractHeatmapDataStep(runner, event)
            expect(response).toEqual([event, []])
            expect(response[0].properties.$heatmap_data).toBeUndefined()
        })
    })
})
