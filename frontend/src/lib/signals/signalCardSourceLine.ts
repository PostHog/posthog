import { errorTrackingSignalHeaderLine } from './errorTracking'

/** Human-readable “Product · Signal type” line for inbox / debug signal cards. */
export function signalCardSourceLine(signal: { source_product: string; source_type: string }): string {
    const { source_product, source_type } = signal

    if (source_product === 'error_tracking') {
        return errorTrackingSignalHeaderLine(source_type)
    }
    if (source_product === 'session_replay' && source_type === 'session_segment_cluster') {
        return 'Session replay · Session segment cluster'
    }
    if (source_product === 'llm_analytics' && source_type === 'evaluation') {
        return 'LLM analytics · Evaluation'
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

    const productLabel = source_product.replace(/_/g, ' ')
    const typeLabel = source_type.replace(/_/g, ' ')
    return `${productLabel} · ${typeLabel}`
}
