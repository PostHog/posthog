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

// Products whose every signal type reads the same.
const SOURCE_LINE_BY_PRODUCT = new Map<string, string>([
    ['session_replay', 'Session replay · Problem segment'],
    ['replay_vision', 'Replay vision · Scanner finding'],
    ['health_checks', 'Health checks · Instrumentation issue'],
])

// Keyed `${source_product}/${source_type}`.
const SOURCE_LINE_BY_PAIR = new Map<string, string>([
    ['llm_analytics/evaluation', 'AI observability · Evaluation'],
    ['llm_analytics/evaluation_report', 'AI observability · Evaluation report'],
    ['zendesk/ticket', 'Zendesk · Ticket'],
    ['github/issue', 'GitHub · Issue'],
    ['linear/issue', 'Linear · Issue'],
    ['conversations/ticket', 'Conversations · Ticket'],
    ['pganalyze/issue', 'pganalyze · Issue'],
    ['endpoints/endpoint_execution_failed', 'Endpoints · Endpoint execution failed'],
    ['logs/alert_state_change', 'Logs · Alert state change'],
    ['analytics/anomaly_investigation', 'Product analytics · Anomaly investigation'],
    ['analytics/alert_firing', 'Product analytics · Alert firing'],
])

/** Human-readable "Product · Signal type" line for inbox / debug signal cards. */
export function signalCardSourceLine(signal: { source_product: string; source_type: string; extra?: unknown }): string {
    const { source_product, source_type } = signal

    if (source_product === 'error_tracking') {
        return errorTrackingSignalHeaderLine(source_type)
    }
    if (source_product === 'signals_scout') {
        const extra = signal.extra as { skill_name?: unknown } | undefined
        const skillName = typeof extra?.skill_name === 'string' ? extra.skill_name : undefined
        const name = scoutDisplayName(skillName)
        return name ? `Scout · ${name}` : 'Scout · Cross-source finding'
    }
    const known =
        SOURCE_LINE_BY_PRODUCT.get(source_product) ?? SOURCE_LINE_BY_PAIR.get(`${source_product}/${source_type}`)
    if (known) {
        return known
    }

    const productLabel = source_product.replace(/_/g, ' ')
    const typeLabel = source_type.replace(/_/g, ' ')
    return `${productLabel} · ${typeLabel}`
}
