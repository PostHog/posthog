import { router } from 'kea-router'

import type { ScatterSeries } from '@posthog/quill-charts'

import { urls } from 'scenes/urls'

import { formatEvalTitle } from './traceSummaryLoader'
import type { ClusteringLevel, TraceSummary } from './types'

/** Per-point data carried through quill's scatter `meta`, handed back on hover and click. */
export interface ClusterScatterMeta {
    traceId?: string
    generationId?: string
    timestamp?: string
    clusterId?: number
    isCentroid?: boolean
}

export type ClusterScatterSeries = ScatterSeries<ClusterScatterMeta>

/** Routes a clicked item point (trace / generation / evaluation) to its trace page. Shared by the
 *  overview and single-cluster plots, which navigate identically for non-centroid points. */
export function navigateToClusterItem(
    meta: ClusterScatterMeta,
    clusteringLevel: ClusteringLevel,
    traceSummaries: Record<string, TraceSummary>
): void {
    if (clusteringLevel === 'evaluation') {
        // point.traceId is the backend's eval-uuid fallback when metadata didn't resolve; routing
        // there 404s. Use the loaded summary's real traceId; no-op until it loads.
        const resolvedTraceId = meta.generationId ? traceSummaries[meta.generationId]?.traceId : undefined
        if (!resolvedTraceId) {
            return
        }
        router.actions.push(
            urls.aiObservabilityTrace(resolvedTraceId, {
                tab: 'summary',
                ...(meta.generationId ? { event: meta.generationId } : {}),
                ...(meta.timestamp ? { timestamp: meta.timestamp } : {}),
            })
        )
        return
    }

    if (meta.traceId) {
        router.actions.push(
            urls.aiObservabilityTrace(meta.traceId, {
                tab: 'summary',
                ...(clusteringLevel === 'generation' && meta.generationId ? { event: meta.generationId } : {}),
                ...(meta.timestamp ? { timestamp: meta.timestamp } : {}),
            })
        )
    }
}

/** Tooltip body line for an item point: the trace/eval summary title once it has loaded. */
export function clusterItemLabel(
    meta: ClusterScatterMeta,
    clusteringLevel: ClusteringLevel,
    traceSummaries: Record<string, TraceSummary>
): string | undefined {
    // Evaluation/generation summaries are keyed by generation_id; trace summaries by trace_id.
    const summaryKey =
        clusteringLevel === 'generation' || clusteringLevel === 'evaluation' ? meta.generationId : meta.traceId
    if (!summaryKey) {
        return undefined
    }
    const summary = traceSummaries[summaryKey]
    if (clusteringLevel === 'evaluation') {
        return formatEvalTitle(summary, 140) || undefined
    }
    return summary?.title || undefined
}

export function clusterItemFooter(meta: ClusterScatterMeta, clusteringLevel: ClusteringLevel): string {
    if (!meta.traceId) {
        return ''
    }
    return clusteringLevel === 'generation' || clusteringLevel === 'evaluation'
        ? 'click to view generation'
        : 'click to view trace'
}

/** Placeholder body line shown until the item's summary loads: a shortened id. */
export function fallbackItemLabel(meta: ClusterScatterMeta, clusteringLevel: ClusteringLevel): string | undefined {
    if (!meta.traceId) {
        return undefined
    }
    const id = (meta.generationId || meta.traceId).slice(0, 8)
    if (clusteringLevel === 'generation') {
        return `Generation ${id}...`
    }
    if (clusteringLevel === 'evaluation') {
        return `Evaluation ${id}...`
    }
    return `Trace ${meta.traceId.slice(0, 8)}...`
}
