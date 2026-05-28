import { createTestEventHeaders } from '../../../../tests/helpers/event-headers'
import { dlq, ok } from '../../pipelines/results'
import { createDenyEventsStep } from './deny-events'

function makeInput(eventName: string) {
    return {
        event: {
            event: {
                event: eventName,
                distinct_id: 'user123',
                team_id: 1,
                ip: '127.0.0.1',
                site_url: 'https://example.com',
                now: '2021-01-01T00:00:00Z',
                uuid: '123e4567-e89b-12d3-a456-426614174000',
            },
            headers: createTestEventHeaders({
                token: 'token123',
                distinct_id: 'user123',
                timestamp: '2021-01-01T00:00:00Z',
            }),
        },
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

    it('passes through everything when the deny list is empty', async () => {
        const emptyStep = createDenyEventsStep([])
        const input = makeInput('$exception')

        const result = await emptyStep(input)

        expect(result).toEqual(ok(input))
    })
})
