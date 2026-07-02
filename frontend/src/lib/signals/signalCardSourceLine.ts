import { errorTrackingSignalHeaderLine } from './errorTracking'

/**
 * Prettifies a scout skill slug for display: strips the `signals-scout-` prefix, turns separators
 * into spaces, and Sentence-cases the result (e.g. `signals-scout-error-tracking` → "Error tracking").
 * Returns null for a bare `signals-scout` / empty slug so callers can fall back.
 */
export function scoutDisplayName(skillName: string | null | undefined): string | null {
    if (!skillName) {
        return null
    }
    const rest = skillName
        .replace(/^signals-scout-?/, '')
        .replace(/[-_]/g, ' ')
        .trim()
    if (!rest) {
        return null
    }
    return rest.charAt(0).toUpperCase() + rest.slice(1)
}

/** Human-readable "Product · Signal type" line for inbox / debug signal cards. */
export function signalCardSourceLine(signal: {
    source_product: string
    source_type: string
    extra?: Record<string, unknown>
}): string {
    const { source_product, source_type } = signal

    if (source_product === 'error_tracking') {
        return errorTrackingSignalHeaderLine(source_type)
    }
    if (source_product === 'session_replay') {
        return 'Session replay · Problem segment'
    }
    if (source_product === 'llm_analytics' && source_type === 'evaluation') {
        return 'AI observability · Evaluation'
    }
    if (source_product === 'llm_analytics' && source_type === 'evaluation_report') {
        return 'AI observability · Evaluation report'
    }
    if (source_product === 'zendesk' && source_type === 'ticket') {
        return 'Zendesk · Ticket'
    }
    if (source_product === 'github' && source_type === 'issue') {
        return 'GitHub · Issue'
    }
    if (source_product === 'linear' && source_type === 'issue') {
        return 'Linear · Issue'
    }
    if (source_product === 'conversations' && source_type === 'ticket') {
        return 'Conversations · Ticket'
    }
    if (source_product === 'pganalyze' && source_type === 'issue') {
        return 'pganalyze · Issue'
    }
    if (source_product === 'endpoints' && source_type === 'endpoint_execution_failed') {
        return 'Endpoints · Endpoint execution failed'
    }
    if (source_product === 'logs' && source_type === 'alert_state_change') {
        return 'Logs · Alert state change'
    }
    if (source_product === 'health_checks') {
        return 'Health checks · Instrumentation issue'
    }
    if (source_product === 'signals_scout') {
        const skillName = typeof signal.extra?.skill_name === 'string' ? signal.extra.skill_name : undefined
        const name = scoutDisplayName(skillName)
        return name ? `Scout · ${name}` : 'Scout · Cross-source finding'
    }

    const productLabel = source_product.replace(/_/g, ' ')
    const typeLabel = source_type.replace(/_/g, ' ')
    return `${productLabel} · ${typeLabel}`
}
