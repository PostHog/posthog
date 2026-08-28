// pydantic-ai and newer OpenLLMetry report the finish reason inside each output message rather
// than as its own span attribute. The generic mapping (or traceloop's reassembly) lands those
// messages in `$ai_output_choices`, so the reason has to be lifted out to survive as a property.

function finishReasonOf(message: unknown): string | undefined {
    if (typeof message !== 'object' || message === null) {
        return undefined
    }
    const reason = (message as { finish_reason?: unknown }).finish_reason
    return typeof reason === 'string' && reason !== '' ? reason : undefined
}

export function liftStopReasonFromOutputChoices(props: Record<string, unknown>): void {
    if (props['$ai_stop_reason'] !== undefined || !Array.isArray(props['$ai_output_choices'])) {
        return
    }
    // The last entry that names a reason describes how the response ended.
    const reason = props['$ai_output_choices'].map(finishReasonOf).findLast((r) => r !== undefined)
    if (reason !== undefined) {
        props['$ai_stop_reason'] = reason
    }
}
