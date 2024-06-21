import { ISOTimestamp, PreIngestionEvent } from '../../../../src/types'
import { cloneObject } from '../../../../src/utils/utils'
import { enrichExceptionEventStep } from '../../../../src/worker/ingestion/event-pipeline/enrichExceptionEventStep'

jest.mock('../../../../src/worker/plugins/run')

const aStackTrace =
    '[{"filename":"http://localhost:8234/static/chunk-VDD5ZZ2W.js","function":"dependenciesChecker","in_app":true,"lineno":721,"colno":42},{"filename":"http://localhost:8234/static/chunk-VDD5ZZ2W.js","function":"?","in_app":true,"lineno":2474,"colno":40},{"filename":"http://localhost:8234/static/chunk-VDD5ZZ2W.js","function":"Object.memoized [as tiles]","in_app":true,"lineno":632,"colno":24},{"filename":"http://localhost:8234/static/chunk-VDD5ZZ2W.js","function":"dependenciesChecker","in_app":true,"lineno":721,"colno":42},{"filename":"http://localhost:8234/static/chunk-VDD5ZZ2W.js","function":"memoized","in_app":true,"lineno":632,"colno":24},{"filename":"http://localhost:8234/static/chunk-VDD5ZZ2W.js","function":"dependenciesChecker","in_app":true,"lineno":721,"colno":42},{"filename":"http://localhost:8234/static/chunk-VDD5ZZ2W.js","function":"logic.selector","in_app":true,"lineno":2517,"colno":18},{"filename":"http://localhost:8234/static/chunk-VDD5ZZ2W.js","function":"pathSelector","in_app":true,"lineno":2622,"colno":37},{"filename":"<anonymous>","function":"Array.reduce","in_app":true},{"filename":"http://localhost:8234/static/chunk-VDD5ZZ2W.js","function":"?","in_app":true,"lineno":2626,"colno":15}]'

const preIngestionEvent: PreIngestionEvent = {
    eventUuid: '018eebf3-cb48-750b-bfad-36409ea6f2b2',
    event: '$exception',
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
    },
    timestamp: '2024-04-17T12:06:46.861Z' as ISOTimestamp,
    teamId: 1,
}

describe('enrichExceptionEvent()', () => {
    let runner: any
    let event: PreIngestionEvent

    beforeEach(() => {
        event = cloneObject(preIngestionEvent)
        runner = {
            hub: {
                kafkaProducer: {
                    produce: jest.fn((e) => Promise.resolve(e)),
                },
            },
            nextStep: (...args: any[]) => args,
        }
    })

    it('ignores non-exception events - even if they have a stack trace', async () => {
        event.event = 'not_exception'
        event.properties['$exception_stack_trace_raw'] = '[{"some": "data"}]'
        expect(event.properties['$exception_fingerprint']).toBeUndefined()

        const response = await enrichExceptionEventStep(runner, event)
        expect(response).toBe(event)
    })

    it('use a fingerprint if it is present', async () => {
        event.event = '$exception'
        event.properties['$exception_stack_trace_raw'] = '[{"some": "data"}]'
        event.properties['$exception_fingerprint'] = 'some-fingerprint'

        const response = await enrichExceptionEventStep(runner, event)

        expect(response.properties['$exception_fingerprint']).toBe('some-fingerprint')
    })

    it('uses the message and stack trace as the simplest grouping', async () => {
        event.event = '$exception'
        event.properties['$exception_message'] = 'some-message'
        event.properties['$exception_stack_trace_raw'] = aStackTrace

        const response = await enrichExceptionEventStep(runner, event)

        expect(response.properties['$exception_fingerprint']).toBe(
            'no-type-provided__some-message__dependenciesChecker'
        )
    })

    it('includes type in stack grouping when present', async () => {
        event.event = '$exception'
        event.properties['$exception_message'] = 'some-message'
        event.properties['$exception_stack_trace_raw'] = aStackTrace
        event.properties['$exception_type'] = 'UnhandledRejection'

        const response = await enrichExceptionEventStep(runner, event)

        expect(response.properties['$exception_fingerprint']).toBe(
            'UnhandledRejection__some-message__dependenciesChecker'
        )
    })

    it('falls back to message and type when no stack trace', async () => {
        event.event = '$exception'
        event.properties['$exception_message'] = 'some-message'
        event.properties['$exception_stack_trace_raw'] = null
        event.properties['$exception_type'] = 'UnhandledRejection'

        const response = await enrichExceptionEventStep(runner, event)

        expect(response.properties['$exception_fingerprint']).toBe('UnhandledRejection__some-message')
    })

    it('adds no fingerprint if no qualifying properties', async () => {
        event.event = '$exception'
        event.properties['$exception_message'] = null
        event.properties['$exception_stack_trace_raw'] = null
        event.properties['$exception_type'] = null

        const response = await enrichExceptionEventStep(runner, event)

        expect(response.properties['$exception_fingerprint']).toBeUndefined()
    })
    // it('additionally parses ', async () => {
    //     event.properties = {
    //         ...event.properties,
    //         $prev_pageview_pathname: '/test',
    //         $prev_pageview_max_scroll: 225,
    //         $prev_pageview_last_content: 1445,
    //         $prev_pageview_max_content: 1553,
    //     }
    //
    //     const response = await extractHeatmapDataStep(runner, event)
    //     // We do delete heatmap data
    //     expect(response[0].properties.$heatmap_data).toBeUndefined()
    //     // We don't delete scroll properties
    //     expect(response[0].properties.$prev_pageview_max_scroll).toEqual(225)
    //
    //     expect(response[1]).toHaveLength(17)
    //
    //     const allParsedMessages = runner.hub.kafkaProducer.produce.mock.calls.map((call) =>
    //         JSON.parse(call[0].value.toString())
    //     )
    //
    //     expect(allParsedMessages.find((x) => x.type === 'scrolldepth')).toMatchInlineSnapshot(`
    //         Object {
    //           "current_url": "http://localhost:3000/test",
    //           "distinct_id": "018eebf3-79b1-7082-a7c6-eeb56a36002f",
    //           "pointer_target_fixed": false,
    //           "scale_factor": 16,
    //           "session_id": "018eebf3-79cd-70da-895f-b6cf352bd688",
    //           "team_id": 1,
    //           "timestamp": "2024-04-17 12:06:46.861",
    //           "type": "scrolldepth",
    //           "viewport_height": 83,
    //           "viewport_width": 67,
    //           "x": 0,
    //           "y": 14,
    //         }
    //     `)
    // })
    //
    // describe('validation', () => {
    //     it('handles empty array $heatmap_data', async () => {
    //         event.properties.$heatmap_data = []
    //         const response = await extractHeatmapDataStep(runner, event)
    //         expect(response).toEqual([event, []])
    //         expect(response[0].properties.$heatmap_data).toBeUndefined()
    //     })
    //
    //     it('handles empty object $heatmap_data', async () => {
    //         event.properties.$heatmap_data = {}
    //         const response = await extractHeatmapDataStep(runner, event)
    //         expect(response).toEqual([event, []])
    //         expect(response[0].properties.$heatmap_data).toBeUndefined()
    //     })
    //
    //     it('ignores events without $heatmap_data', async () => {
    //         event.properties.$heatmap_data = null
    //         const response = await extractHeatmapDataStep(runner, event)
    //         expect(response).toEqual([event, []])
    //         expect(response[0].properties.$heatmap_data).toBeUndefined()
    //     })
    //
    //     it('ignores events with bad $heatmap_data', async () => {
    //         event.properties.$heatmap_data = 'wat'
    //         const response = await extractHeatmapDataStep(runner, event)
    //         expect(response).toEqual([event, []])
    //         expect(response[0].properties.$heatmap_data).toBeUndefined()
    //     })
    //
    //     it.each([
    //         [
    //             {
    //                 '    ': [
    //                     {
    //                         x: 1020,
    //                         y: 363,
    //                         target_fixed: false,
    //                         type: 'mousemove',
    //                     },
    //                 ],
    //             },
    //         ],
    //         [
    //             {
    //                 'x must be a number': [
    //                     {
    //                         x: '1020',
    //                         y: 363,
    //                         target_fixed: false,
    //                         type: 'mousemove',
    //                     },
    //                 ],
    //             },
    //         ],
    //         [
    //             {
    //                 'y must be a number': [
    //                     {
    //                         x: 1020,
    //                         y: '363',
    //                         target_fixed: false,
    //                         type: 'mousemove',
    //                     },
    //                 ],
    //             },
    //         ],
    //         [
    //             {
    //                 'type must be present': [
    //                     {
    //                         x: 1020,
    //                         y: 363,
    //                         target_fixed: false,
    //                         type: '     ',
    //                     },
    //                 ],
    //             },
    //         ],
    //     ])('only includes valid heatmap data', async (invalidEvent) => {
    //         event.properties.$heatmap_data = invalidEvent
    //         const response = await extractHeatmapDataStep(runner, event)
    //         expect(response).toEqual([event, []])
    //         expect(response[0].properties.$heatmap_data).toBeUndefined()
    //     })
    // })
})
