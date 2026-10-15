import { dlq, ok } from '~/ingestion/framework/results'
import { createTestEventHeaders } from '~/tests/helpers/event-headers'

import { createAllowEventPrefixStep, createAllowEventsStep } from './allow-events'

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

    describe('createAllowEventPrefixStep', () => {
        const prefixStep = createAllowEventPrefixStep('$ai_')

        it.each(['$ai_generation', '$ai_custom_metric', '$ai_'])('passes through %s', async (eventName) => {
            const input = makeInput(eventName)

            expect(await prefixStep(input)).toEqual(ok(input))
        })

        it.each(['$pageview', 'ai_generation', '$AI_generation', ' $ai_generation', '$ai'])(
            'DLQs %s with the prefix mismatch reason',
            async (eventName) => {
                expect(await prefixStep(makeInput(eventName))).toEqual(dlq('event_name_prefix_mismatch'))
            }
        )

        it('passes through events with no event header (no name to match)', async () => {
            const input = makeInput(undefined)

            expect(await prefixStep(input)).toEqual(ok(input))
        })
    })
})
