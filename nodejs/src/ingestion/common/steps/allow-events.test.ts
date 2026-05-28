import { createTestEventHeaders } from '../../../../tests/helpers/event-headers'
import { dlq, ok } from '../../pipelines/results'
import { createAllowEventsStep } from './allow-events'

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

    it('DLQs every event when the allow list is empty', async () => {
        const emptyStep = createAllowEventsStep([])

        const result = await emptyStep(makeInput('$pageview'))

        expect(result).toEqual(dlq('event_not_in_allowlist'))
    })
})
