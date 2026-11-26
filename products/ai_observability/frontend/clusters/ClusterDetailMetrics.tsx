import { useValues } from 'kea'

import { LemonCard, LemonSkeleton, Tooltip } from '@posthog/lemon-ui'

import { formatErrorRate, formatLLMCost, formatLLMLatency } from '../utils'
import { clusterDetailLogic } from './clusterDetailLogic'

export function ClusterDetailMetrics(): JSX.Element {
    const {
        cluster,
        clusterData,
        clusteringLevel,
        clusterMetrics: metrics,
        clusterMetricsLoading,
    } = useValues(clusterDetailLogic)
    const items = [
        {
            label:
                clusteringLevel === 'trace'
                    ? 'Traces'
                    : clusteringLevel === 'generation'
                      ? 'Generations'
                      : 'Evaluations',
            value: cluster?.size.toLocaleString(),
        },
        {
            label: 'Share',
            value:
                cluster && clusterData?.totalItemsAnalyzed
                    ? `${Math.round((cluster.size / clusterData.totalItemsAnalyzed) * 100)}%`
                    : '—',
            tooltip: 'Share of all items analyzed in this run.',
        },
        {
            label: 'Avg. cost',
            value: metrics?.avgCost != null ? formatLLMCost(metrics.avgCost) : '—',
            tooltip:
                clusteringLevel === 'evaluation'
                    ? 'Average cost of the linked generations.'
                    : 'Average cost across this cluster.',
        },
        {
            label: 'Avg. latency',
            value: metrics?.avgLatency != null ? formatLLMLatency(metrics.avgLatency) : '—',
            tooltip:
                clusteringLevel === 'evaluation'
                    ? 'Average latency of the linked generations.'
                    : 'Average latency across this cluster.',
        },
        {
            label: clusteringLevel === 'evaluation' ? 'Pass rate' : 'Errors',
            value:
                clusteringLevel === 'evaluation'
                    ? metrics?.passRate != null
                        ? formatErrorRate(metrics.passRate)
                        : '—'
                    : metrics?.errorRate != null
                      ? formatErrorRate(metrics.errorRate)
                      : '—',
            tooltip:
                clusteringLevel === 'evaluation'
                    ? 'Share of evaluations that passed across this cluster.'
                    : 'Share of items with errors across this cluster.',
        },
    ]

    return (
        <LemonCard hoverEffect={false} className="p-0 grid grid-cols-2 @[600px]:grid-cols-5 divide-x">
            {items.map(({ label, value, tooltip }, index) => (
                <Tooltip key={label} title={tooltip}>
                    <div className="p-3 min-w-0">
                        <div className="text-xs text-muted whitespace-nowrap mb-1">{label}</div>
                        {clusterMetricsLoading && index > 1 ? (
                            <LemonSkeleton className="h-6 w-12" />
                        ) : (
                            <div className="text-lg font-semibold tabular-nums">{value}</div>
                        )}
                    </div>
                </Tooltip>
            ))}
        </LemonCard>
    )
}
