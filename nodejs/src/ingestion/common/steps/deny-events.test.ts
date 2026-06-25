import { dlq, ok } from '~/ingestion/framework/results'
import { createTestEventHeaders } from '~/tests/helpers/event-headers'

import { createDenyEventsStep } from './deny-events'

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

describe('createDenyEventsStep', () => {
    const step = createDenyEventsStep(['$exception', '$$client_ingestion_warning'])

    it('DLQs events whose name is in the deny list', async () => {
        const result = await step(makeInput('$exception'))

        expect(result).toEqual(dlq('event_in_denylist'))
    })

    it('DLQs every denied event type', async () => {
        const result = await step(makeInput('$$client_ingestion_warning'))

        expect(result).toEqual(dlq('event_in_denylist'))
    })

    it('passes through events whose name is not in the deny list', async () => {
        const input = makeInput('$pageview')

        const result = await step(input)

        expect(result).toEqual(ok(input))
    })

    it('passes through events with no event header (no name to match)', async () => {
        const input = makeInput(undefined)

        const result = await step(input)

        expect(result).toEqual(ok(input))
    })

    it('passes through everything when the deny list is empty', async () => {
        const emptyStep = createDenyEventsStep([])
        const input = makeInput('$exception')

        const result = await emptyStep(input)

        expect(result).toEqual(ok(input))
    })
})
