import { AI_EVENTS_USAGE_KEY, EVENTS_USAGE_KEY, resolveAiUsageKey, resolveAnalyticsUsageKey } from './billable-events'

describe('usage key resolvers', () => {
    it.each([
        ['$pageview', EVENTS_USAGE_KEY],
        ['custom event', EVENTS_USAGE_KEY],
        ['$ai_generation', AI_EVENTS_USAGE_KEY],
        ['$ai_trace_clusters', AI_EVENTS_USAGE_KEY],
        ['$feature_flag_called', null],
        ['$experiment_exposure', null],
        ['survey sent', null],
        ['$exception', null],
        ['$conversations_message_sent', null],
    ])('resolveAnalyticsUsageKey bills %s under %s', (event, expected) => {
        expect(resolveAnalyticsUsageKey(event)).toBe(expected)
    })

    it('bills everything on the ai lane under the ai key', () => {
        expect(resolveAiUsageKey('$ai_generation')).toBe(AI_EVENTS_USAGE_KEY)
        expect(resolveAiUsageKey('$ai_evaluation_report')).toBe(AI_EVENTS_USAGE_KEY)
    })
})
