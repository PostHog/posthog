/**
 * Assertion types + helpers — frontend-only because `assertions` is a JSONField
 * on the backend (no DRF serializer = no generated schema).
 *
 * All assertions are evaluated server-side against the agent's *own* PostHog session
 * (scoped via `run.posthog_session_id`), so a real user firing the same event at the
 * same time won't false-positive.
 */

export type AgenticTestAssertion =
    | { type: 'event_captured'; event: string; within_seconds: number }
    | { type: 'event_not_captured'; event: string; within_seconds: number }
    | { type: 'no_console_errors'; max_errors: number }

export type AgenticTestAssertionType = AgenticTestAssertion['type']

export interface AgenticTestAssertionResult {
    type: AgenticTestAssertionType
    passed: boolean
    message: string
    config: AgenticTestAssertion
}

export const ASSERTION_TYPE_LABELS: Record<AgenticTestAssertionType, string> = {
    event_captured: 'Event captured',
    event_not_captured: 'Event NOT captured',
    no_console_errors: 'No console errors',
}

export function defaultAssertion(type: AgenticTestAssertionType): AgenticTestAssertion {
    switch (type) {
        case 'event_captured':
            return { type: 'event_captured', event: '', within_seconds: 30 }
        case 'event_not_captured':
            return { type: 'event_not_captured', event: '', within_seconds: 30 }
        case 'no_console_errors':
            return { type: 'no_console_errors', max_errors: 0 }
    }
}
