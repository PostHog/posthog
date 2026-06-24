import { errorTrackingSignalHeaderLine } from './errorTracking'

/** Human-readable "Product · Signal type" line for inbox / debug signal cards. */
export function signalCardSourceLine(signal: { source_product: string; source_type: string }): string {
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
        return 'Scout · Cross-source finding'
    }

    const productLabel = source_product.replace(/_/g, ' ')
    const typeLabel = source_type.replace(/_/g, ' ')
    return `${productLabel} · ${typeLabel}`
}
