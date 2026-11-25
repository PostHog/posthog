import type { CohortRealtimeReadinessApi } from '../generated/api.schemas'
import { unpreparableExplanation } from './realtimeReadiness'

const readiness = (
    state: CohortRealtimeReadinessApi['state'],
    overrides: Partial<CohortRealtimeReadinessApi> = {}
): CohortRealtimeReadinessApi => ({
    state,
    ready_at: null,
    build: null,
    reason: null,
    history_limit_days: null,
    ...overrides,
})

describe('unpreparableExplanation', () => {
    it.each([
        {
            name: 'off with an unsupported time range',
            realtime: readiness('off', { reason: 'unsupported_time_range' }),
            explains:
                /^Realtime can't be turned on for this cohort, so feature flags can't target it\. One of its event criteria uses a time range/,
        },
        {
            name: 'off past the plan history limit',
            realtime: readiness('off', { reason: 'history_over_limit', history_limit_days: 30 }),
            explains:
                /^Realtime can't be turned on for this cohort, so feature flags can't target it\. Realtime cohorts on your plan can look back at most 30 days/,
        },
        {
            name: 'needs_attention with an unsupported time range',
            realtime: readiness('needs_attention', { reason: 'unsupported_time_range' }),
            explains: /^Feature flags can't target this cohort\. One of its event criteria uses a time range/,
        },
        { name: 'off with no reason', realtime: readiness('off'), explains: null },
        {
            name: 'needs_attention too large to build',
            realtime: readiness('needs_attention', { reason: 'too_large_to_build' }),
            explains: null,
        },
    ])('explains a cohort that is $name', ({ realtime, explains }) => {
        const explanation = unpreparableExplanation(realtime)

        if (explains === null) {
            expect(explanation).toBeNull()
        } else {
            expect(explanation).toMatch(explains)
        }
    })
})
