import { dlq, ok } from '~/ingestion/framework/results'
import { createTestEventHeaders } from '~/tests/helpers/event-headers'

import { createAllowEventsStep } from './allow-events'

function makeInput(eventName: string | undefined) {
    return {
        headers: createTestEventHeaders({
            token: 'token123',
            distinct_id: 'user123',
            timestamp: '2021-01-01T00:00:00Z',
            event: eventName,
        }),
    }
}

describe('createAllowEventsStep', () => {
    const step = createAllowEventsStep({ eventNames: ['$$client_ingestion_warning'] })

    it('passes through events whose name is in the allow list', async () => {
        const input = makeInput('$$client_ingestion_warning')

        const result = await step(input)

        expect(result).toEqual(ok(input))
    })

    it('DLQs events whose name is not in the allow list', async () => {
        const input = makeInput('$pageview')

        const result = await step(input)

        expect(result).toEqual(dlq('event_not_in_allowlist'))
    })

    it('passes through events with no event header (no name to match)', async () => {
        const input = makeInput(undefined)

        const result = await step(input)

        expect(result).toEqual(ok(input))
    })

    it('DLQs every named event when nothing is allowed', async () => {
        const emptyStep = createAllowEventsStep({})

        const result = await emptyStep(makeInput('$pageview'))

        expect(result).toEqual(dlq('event_not_in_allowlist'))
    })

    test.each([
        ['$ai_generation', true],
        ['$ai_tag', true],
        ['$ai_', true],
        ['$aiproduct_event', false],
        ['$pageview', false],
    ])('eventPrefixes matches by prefix: %s allowed=%s', async (eventName, allowed) => {
        const prefixStep = createAllowEventsStep({ eventPrefixes: ['$ai_'] })
        const input = makeInput(eventName)

        const result = await prefixStep(input)

        expect(result).toEqual(allowed ? ok(input) : dlq('event_not_in_allowlist'))
    })
})
