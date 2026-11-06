// pydantic-ai and newer OpenLLMetry report the finish reason inside each output message rather
// than as its own span attribute. The generic mapping (or traceloop's reassembly) lands those
// messages in `$ai_output_choices`, so the reason has to be lifted out to survive as a property.

// Real finish reasons are short enum-like strings. The cap keeps a malformed or hostile attribute
// from landing a blob in $ai_stop_reason, matching the size guards on other parsed OTel payloads.
const MAX_STOP_REASON_LENGTH = 128

export function usableStopReason(value: unknown): string | undefined {
    return typeof value === 'string' && value !== '' && value.length <= MAX_STOP_REASON_LENGTH ? value : undefined
}

function finishReasonOf(message: unknown): string | undefined {
    if (typeof message !== 'object' || message === null) {
        return undefined
    }
    return usableStopReason((message as { finish_reason?: unknown }).finish_reason)
}

export function liftStopReasonFromOutputChoices(props: Record<string, unknown>): void {
    if (props['$ai_stop_reason'] !== undefined || !Array.isArray(props['$ai_output_choices'])) {
        return
    }
    // Every carrier that lands here holds one entry per choice, never sequential parts of one
    // response: the GenAI semconv defines output messages as choices, and pydantic-ai asserts a
    // single one per span. Take the first named reason, the choice the trace view renders first,
    // matching the flat `finish_reasons[0]` reads.
    const reason = props['$ai_output_choices'].map(finishReasonOf).find((r) => r !== undefined)
    if (reason !== undefined) {
        props['$ai_stop_reason'] = reason
    }
}
