import { ISOTimestamp, PreIngestionEvent } from '../../../../src/types'
import { cloneObject } from '../../../../src/utils/utils'
import { enrichExceptionEventStep } from '../../../../src/worker/ingestion/event-pipeline/enrichExceptionEventStep'

jest.mock('../../../../src/worker/plugins/run')

const DEFAULT_EXCEPTION_LIST = [
    {
        mechanism: {
            handled: true,
            type: 'generic',
            synthetic: false,
        },
        stacktrace: {
            frames: [
                {
                    colno: 220,
                    filename: 'https://app-static-prod.posthog.com/static/chunk-UFQKIDIH.js',
                    function: 'submitZendeskTicket',
                    in_app: true,
                    lineno: 25,
                },
            ],
        },
        type: 'Error',
        value: 'There was an error creating the support ticket with zendesk.',
    },
]

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
        event.properties['$exception_list'] = DEFAULT_EXCEPTION_LIST
        expect(event.properties['$exception_fingerprint']).toBeUndefined()

        const response = await enrichExceptionEventStep(runner, event)
        expect(response).toBe(event)
    })

    it('use a fingerprint if it is present', async () => {
        event.event = '$exception'
        event.properties['$exception_list'] = DEFAULT_EXCEPTION_LIST

        event.properties['$exception_fingerprint'] = 'some-fingerprint'

        const response = await enrichExceptionEventStep(runner, event)

        expect(response.properties['$exception_fingerprint']).toBe('some-fingerprint')
    })

    it('uses the message and stack trace as the simplest grouping', async () => {
        event.event = '$exception'
        event.properties['$exception_message'] = 'some-message'
        event.properties['$exception_list'] = DEFAULT_EXCEPTION_LIST

        const response = await enrichExceptionEventStep(runner, event)

        expect(response.properties['$exception_fingerprint']).toStrictEqual([
            'Error',
            'some-message',
            'submitZendeskTicket',
        ])
    })

    it('includes type in stack grouping when present', async () => {
        event.event = '$exception'
        event.properties['$exception_message'] = 'some-message'
        event.properties['$exception_list'] = DEFAULT_EXCEPTION_LIST
        event.properties['$exception_type'] = 'UnhandledRejection'

        const response = await enrichExceptionEventStep(runner, event)

        expect(response.properties['$exception_fingerprint']).toStrictEqual([
            'UnhandledRejection',
            'some-message',
            'submitZendeskTicket',
        ])
    })

    it('falls back to message and type when no stack trace', async () => {
        event.event = '$exception'
        event.properties['$exception_message'] = 'some-message'
        event.properties['$exception_list'] = null
        event.properties['$exception_type'] = 'UnhandledRejection'

        const response = await enrichExceptionEventStep(runner, event)

        expect(response.properties['$exception_fingerprint']).toStrictEqual(['UnhandledRejection', 'some-message'])
    })

    it('adds no fingerprint if no qualifying properties', async () => {
        event.event = '$exception'
        event.properties['$exception_message'] = null
        event.properties['$exception_list'] = null
        event.properties['$exception_type'] = null

        const response = await enrichExceptionEventStep(runner, event)

        expect(response.properties['$exception_fingerprint']).toBeUndefined()
    })

    it('uses exception_list to generate message, type, and fingerprint when not present', async () => {
        event.event = '$exception'
        event.properties['$exception_list'] = DEFAULT_EXCEPTION_LIST

        const response = await enrichExceptionEventStep(runner, event)

        expect(response.properties['$exception_fingerprint']).toStrictEqual([
            'Error',
            'There was an error creating the support ticket with zendesk.',
            'submitZendeskTicket',
        ])
    })

    it('exception_type overrides exception_list to generate fingerprint when present', async () => {
        event.event = '$exception'
        event.properties['$exception_list'] = DEFAULT_EXCEPTION_LIST
        event.properties['$exception_type'] = 'UnhandledRejection'

        const response = await enrichExceptionEventStep(runner, event)

        expect(response.properties['$exception_fingerprint']).toStrictEqual([
            'UnhandledRejection',
            'There was an error creating the support ticket with zendesk.',
            'submitZendeskTicket',
        ])
    })
})
