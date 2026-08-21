import { AI_EVENT_TYPES } from '~/ingestion/common/ai-event-types'

export const EVENTS_USAGE_KEY = 'events'
export const AI_EVENTS_USAGE_KEY = 'ai_events'
export const EXCEPTIONS_USAGE_KEY = 'exceptions'

/** Null means the event is not billed at all. */
export type UsageKeyResolver = (event: string) => string | null

// Mirrors BILLABLE_EVENT_EXCLUDED_EVENTS in posthog/tasks/usage_report.py, minus the AI events,
// which are billed under their own key rather than excluded. The two lists have to agree or the
// usage records and the org usage report bill the same team differently.
const NON_BILLABLE_EVENTS = new Set([
    '$feature_flag_called',
    '$experiment_exposure',
    'survey sent',
    'survey shown',
    'survey dismissed',
    '$exception',
    '$conversations_loaded',
    '$conversations_widget_loaded',
    '$conversations_message_sent',
    '$conversations_user_identified',
    '$conversations_restore_link_requested',
    '$conversations_widget_state_changed',
    '$conversations_back_to_tickets',
])

/**
 * Bills each event under the key its own product owns, wherever the event turns up.
 * Matching the exact AI event names rather than the `$ai_` prefix keeps an unknown
 * `$ai_*` event billable as a standard event, which is what the nightly report does.
 */
export const resolveAnalyticsUsageKey: UsageKeyResolver = (event) => {
    if (AI_EVENT_TYPES.has(event)) {
        return AI_EVENTS_USAGE_KEY
    }
    return NON_BILLABLE_EVENTS.has(event) ? null : EVENTS_USAGE_KEY
}

export const resolveAiUsageKey: UsageKeyResolver = () => AI_EVENTS_USAGE_KEY

export const resolveExceptionUsageKey: UsageKeyResolver = () => EXCEPTIONS_USAGE_KEY
