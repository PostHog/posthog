import { prettifyScoutSkillName } from '@posthog/agent-contracts/scout-names'

import { errorTrackingSignalHeaderLine } from './errorTracking'

/**
 * The fallback name for a scout slug (`signals-scout-mcp-tool-calls` → "MCP tool calls"). Returns null for
 * a bare/empty `signals-scout` slug so callers can fall back. Prefer the team's display name when a caller
 * can look it up.
 */
export function scoutNameFromSlug(skillName: string | null | undefined): string | null {
    if (!skillName || /^signals-scout-?$/.test(skillName)) {
        return null
    }
    return prettifyScoutSkillName(skillName)
}

// Products whose every signal type reads the same.
const SOURCE_LINE_BY_PRODUCT = new Map<string, string>([
    ['session_replay', 'Session replay · Problem segment'],
    ['replay_vision', 'Replay vision · Scanner finding'],
    ['health_checks', 'Health checks · Instrumentation issue'],
    ['user_authored', 'Team member'],
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

/**
 * Human-readable "Product · Signal type" line for inbox / debug signal cards. Pass `scoutNames` (skill
 * name → display name) so a scout's team-set name wins over its prettified slug.
 */
export function signalCardSourceLine(
    signal: { source_product: string; source_type: string; extra?: unknown },
    scoutNames?: Readonly<Record<string, string>>
): string {
    const { source_product, source_type } = signal

    if (source_product === 'error_tracking') {
        return errorTrackingSignalHeaderLine(source_type)
    }
    if (source_product === 'signals_scout') {
        const extra = signal.extra as { skill_name?: unknown } | undefined
        const skillName = typeof extra?.skill_name === 'string' ? extra.skill_name : undefined
        const name = (skillName && scoutNames?.[skillName]) || scoutNameFromSlug(skillName)
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
