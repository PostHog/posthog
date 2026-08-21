import { AI_EVENTS_USAGE_KEY, EVENTS_USAGE_KEY, resolveAiUsageKey, resolveAnalyticsUsageKey } from './billable-events'

describe('usage key resolvers', () => {
    it.each([
        ['$pageview', EVENTS_USAGE_KEY],
        ['custom event', EVENTS_USAGE_KEY],
        ['$ai_generation', AI_EVENTS_USAGE_KEY],
        ['$ai_trace', AI_EVENTS_USAGE_KEY],
        // Not a known AI event name, so it bills as a standard event — matching the nightly report,
        // which excludes the exact AIEventType values rather than everything prefixed `$ai_`.
        ['$ai_not_a_real_event', EVENTS_USAGE_KEY],
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
        expect(resolveAiUsageKey('$ai_not_a_real_event')).toBe(AI_EVENTS_USAGE_KEY)
    })
})
