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
    const step = createAllowEventsStep(['$$client_ingestion_warning'])

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

    it('DLQs every named event when the allow list is empty', async () => {
        const emptyStep = createAllowEventsStep([])

        const result = await emptyStep(makeInput('$pageview'))

        expect(result).toEqual(dlq('event_not_in_allowlist'))
    })
})
