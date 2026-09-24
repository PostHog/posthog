import {
    AI_EVENTS_USAGE_KEY,
    EVENTS_USAGE_KEY,
    SURVEY_RESPONSES_USAGE_KEY,
    resolveAiUsageKey,
    resolveAnalyticsUsageKey,
} from './billable-events'

describe('usage key resolvers', () => {
    it.each([
        ['$pageview', EVENTS_USAGE_KEY],
        ['custom event', EVENTS_USAGE_KEY],
        ['$ai_generation', AI_EVENTS_USAGE_KEY],
        ['$ai_trace', AI_EVENTS_USAGE_KEY],
        // Any `$ai_*` name bills as an AI event, matching the nightly report's prefix split.
        ['$ai_not_a_real_event', AI_EVENTS_USAGE_KEY],
        ['ai_generation', EVENTS_USAGE_KEY],
        ['$AI_generation', EVENTS_USAGE_KEY],
        ['$feature_flag_called', null],
        ['$experiment_exposure', null],
        ['survey sent', SURVEY_RESPONSES_USAGE_KEY],
        ['$exception', null],
        ['$llm_prompt_fetched', null],
        ['$conversations_message_sent', null],
    ])('resolveAnalyticsUsageKey bills %s under %s', (event, expected) => {
        expect(resolveAnalyticsUsageKey(event)).toBe(expected)
    })

    it('bills everything on the ai lane under the ai key', () => {
        expect(resolveAiUsageKey('$ai_generation')).toBe(AI_EVENTS_USAGE_KEY)
        expect(resolveAiUsageKey('$ai_not_a_real_event')).toBe(AI_EVENTS_USAGE_KEY)
    })
})
