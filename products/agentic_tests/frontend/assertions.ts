/**
 * Assertion types + helpers — frontend-only because `assertions` is a JSONField
 * on the backend (no DRF serializer = no generated schema).
 */

export type AgenticTestAssertion =
    | { type: 'url_contains'; value: string }
    | { type: 'event_captured'; event: string; within_seconds: number }

export type AgenticTestAssertionType = AgenticTestAssertion['type']

export interface AgenticTestAssertionResult {
    type: AgenticTestAssertionType
    passed: boolean
    message: string
    config: AgenticTestAssertion
}

export const ASSERTION_TYPE_LABELS: Record<AgenticTestAssertionType, string> = {
    url_contains: 'URL contains',
    event_captured: 'Event captured',
}

export function defaultAssertion(type: AgenticTestAssertionType): AgenticTestAssertion {
    switch (type) {
        case 'url_contains':
            return { type: 'url_contains', value: '' }
        case 'event_captured':
            return { type: 'event_captured', event: '', within_seconds: 30 }
    }
}
