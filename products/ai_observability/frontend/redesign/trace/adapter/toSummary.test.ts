import { LLMTracePerson } from '~/queries/schema/schema-general'

import { makeTrace } from './testFixtures'
import { toSummary } from './toSummary'

describe('toSummary', () => {
    it.each<{
        description: string
        person: LLMTracePerson | null
        expectedLabel: string
    }>([
        {
            description: 'email present',
            person: {
                uuid: 'p1',
                created_at: '',
                distinct_id: 'user-ana',
                properties: { email: 'ana@example.com' },
            },
            expectedLabel: 'ana@example.com',
        },
        {
            description: 'only name present',
            person: {
                uuid: 'p2',
                created_at: '',
                distinct_id: 'user-bob',
                properties: { name: 'Bob' },
            },
            expectedLabel: 'Bob',
        },
        {
            description: 'no person',
            person: null,
            expectedLabel: 'user-ana',
        },
    ])('labels the person by email, then name, then distinct id ($description)', ({ person, expectedLabel }) => {
        const summary = toSummary(makeTrace(), person)
        expect(summary.person?.label).toBe(expectedLabel)
    })

    it('keeps totals null rather than 0 when the trace has no cost or latency', () => {
        const totals = toSummary(makeTrace({ totalCost: undefined, totalLatency: undefined }), null).totals
        expect(totals.costUsd).toBeNull()
        expect(totals.latencyMs).toBeNull()
    })
})
