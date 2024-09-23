import { createHash } from 'node:crypto'

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

        expect(response.properties['$exception_fingerprint']).toStrictEqual(['some-message', 'dependenciesChecker'])
    })

    it('includes type in stack grouping when present', async () => {
        event.event = '$exception'
        event.properties['$exception_message'] = 'some-message'
        event.properties['$exception_stack_trace_raw'] = aStackTrace
        event.properties['$exception_type'] = 'UnhandledRejection'

        const response = await enrichExceptionEventStep(runner, event)

        expect(response.properties['$exception_fingerprint']).toStrictEqual([
            'UnhandledRejection',
            'some-message',
            'dependenciesChecker',
        ])
    })

    it('falls back to message and type when no stack trace', async () => {
        event.event = '$exception'
        event.properties['$exception_message'] = 'some-message'
        event.properties['$exception_stack_trace_raw'] = null
        event.properties['$exception_type'] = 'UnhandledRejection'

        const response = await enrichExceptionEventStep(runner, event)

        expect(response.properties['$exception_fingerprint']).toStrictEqual(['UnhandledRejection', 'some-message'])
    })

    it('adds no fingerprint if no qualifying properties', async () => {
        event.event = '$exception'
        event.properties['$exception_message'] = null
        event.properties['$exception_stack_trace_raw'] = null
        event.properties['$exception_type'] = null

        const response = await enrichExceptionEventStep(runner, event)

        expect(response.properties['$exception_fingerprint']).toBeUndefined()
    })

    it('generates a hash for the exception', async () => {
        event.event = '$exception'
        event.properties['$exception_message'] = 'some-message'
        event.properties['$exception_stack_trace_raw'] = aStackTrace
        event.properties['$exception_type'] = 'UnhandledRejection'

        const event2 = cloneObject(event)

        const response = await enrichExceptionEventStep(runner, event)

        expect(response.properties['$exception_hash']).toBe(
            'e28414be565184223dac022aba1fef779b2579c7c29d0a9982f0e7ef63f7e905'
        )

        // Ensure the hash is deterministic
        delete event.properties['$exception_fingerprint']
        const response2 = await enrichExceptionEventStep(runner, event)
        expect(response2.properties['$exception_hash']).toBe(response.properties['$exception_hash'])

        // Ensure the hash is different for different exceptions
        event2.properties['$exception_message'] = 'some-other-message'
        event2.properties['$exception_type'] = 'SomeOtherException'
        const response3 = await enrichExceptionEventStep(runner, event2)
        expect(response3.properties['$exception_hash']).not.toBe(response.properties['$exception_hash'])
        expect(response3.properties['$exception_hash']).toBe(
            'b7d5ae00e4add0a01021ba696a080ea0f168676ca28b59b9f9ea1dc4e05f12b4'
        )
    })

    it('generates a hash for the exception even if no stack trace', async () => {
        event.event = '$exception'
        event.properties['$exception_message'] = 'some-message'
        event.properties['$exception_stack_trace_raw'] = null
        event.properties['$exception_type'] = 'UnhandledRejection'

        const response = await enrichExceptionEventStep(runner, event)

        expect(response.properties['$exception_hash']).toBe(
            '3043eb0703dbd847af3b592ce14ffbc9aecb528b1ba5ae15c1c6838826a96ee7'
        )
    })

    it('generates a empty hash for empty exception', async () => {
        event.event = '$exception'
        const response = await enrichExceptionEventStep(runner, event)

        expect(response.properties['$exception_hash']).toBe(
            'd8156bae0c4243d3742fc4e9774d8aceabe0410249d720c855f98afc88ff846c'
        )

        expect(createHash('sha256').update('--').digest('hex')).toBe(response.properties['$exception_hash'])
    })
})
