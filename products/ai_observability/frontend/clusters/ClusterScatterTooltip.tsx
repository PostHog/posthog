import { TooltipFooter, TooltipSurface, TooltipSwatch } from '@posthog/quill-charts'
import type { ScatterPointDatum } from '@posthog/quill-charts'

import { formatLLMCost, formatLLMLatency } from '../utils'
import type { ItemMetrics } from './clusterMetricsLoader'
import { clusterItemFooter, clusterItemLabel, fallbackItemLabel } from './clusterScatter'
import type { ClusterScatterMeta } from './clusterScatter'
import type { Cluster, ClusteringLevel, TraceSummary } from './types'

function TooltipShell({
    color,
    title,
    subtitle,
    footer,
    metrics,
}: {
    color: string
    title: string
    subtitle?: string
    footer?: string
    metrics?: ItemMetrics
}): JSX.Element {
    return (
        <TooltipSurface>
            <div className="flex items-center gap-2 min-w-0 font-semibold">
                <TooltipSwatch color={color} />
                <span className="truncate">{title}</span>
            </div>
            {subtitle ? <div className="opacity-60">{subtitle}</div> : null}
            <div className="flex items-center gap-3 text-xs mt-1">
                <span className="text-muted">Cost {metrics?.cost != null ? formatLLMCost(metrics.cost) : '—'}</span>
                <span className="text-muted">
                    Latency {metrics?.latency != null ? formatLLMLatency(metrics.latency) : '—'}
                </span>
                <span className={metrics?.errorCount ? 'text-danger' : 'text-muted'}>
                    {metrics
                        ? metrics.errorCount
                            ? `${metrics.errorCount} ${metrics.errorCount === 1 ? 'error' : 'errors'}`
                            : 'No errors'
                        : 'Errors —'}
                </span>
            </div>
            {footer ? <TooltipFooter>{footer}</TooltipFooter> : null}
        </TooltipSurface>
    )
}

export function ClusterDetailTooltip({
    point,
    cluster,
    clusteringLevel,
    traceSummaries,
}: {
    point: ScatterPointDatum<ClusterScatterMeta>
    cluster: Cluster | null
    clusteringLevel: ClusteringLevel
    traceSummaries: Record<string, TraceSummary>
}): JSX.Element {
    const meta = point.meta ?? {}
    if (meta.isCentroid) {
        return <TooltipShell color={point.color} title="Cluster centroid" subtitle="Center of this cluster" />
    }
    return (
        <TooltipShell
            color={point.color}
            title={cluster?.title ?? point.seriesLabel}
            subtitle={
                clusterItemLabel(meta, clusteringLevel, traceSummaries) ?? fallbackItemLabel(meta, clusteringLevel)
            }
            footer={clusterItemFooter(meta, clusteringLevel)}
            metrics={meta.metrics}
        />
    )
}

export function ClusterOverviewTooltip({
    point,
    clusteringLevel,
    traceSummaries,
}: {
    point: ScatterPointDatum<ClusterScatterMeta>
    clusteringLevel: ClusteringLevel
    traceSummaries: Record<string, TraceSummary>
}): JSX.Element {
    const meta = point.meta ?? {}
    if (meta.isCentroid) {
        return (
            <TooltipShell
                color={point.color}
                title={point.seriesLabel.replace(' (centroid)', '')}
                subtitle="Cluster centroid"
                footer="click to view cluster"
            />
        )
    }
    return (
        <TooltipShell
            color={point.color}
            title={point.seriesLabel}
            subtitle={clusterItemLabel(meta, clusteringLevel, traceSummaries)}
            footer={clusterItemFooter(meta, clusteringLevel)}
            metrics={meta.metrics}
        />
    )
}
