import { match } from 'ts-pattern'

import { IconArrowRight } from '@posthog/icons'

import { Tooltip } from 'lib/lemon-ui/Tooltip'

import type { ExperimentMetric } from '~/queries/schema/schema-general'
import type {
    ExperimentFunnelMetric,
    ExperimentMeanMetric,
    ExperimentMetricSource,
    ExperimentRatioMetric,
} from '~/queries/schema/schema-general'
import {
    isExperimentFunnelMetric,
    isExperimentMeanMetric,
    isExperimentRatioMetric,
} from '~/queries/schema/schema-general'
import { isActionsNode, isDataWarehouseNode, isEventsNode } from '~/queries/utils'

const getSourceName = (source: ExperimentMetricSource): string =>
    match(source)
        .when(isEventsNode, (node) => node.name || node.event || 'Unknown event')
        .when(isActionsNode, (node) => node.name || `Action ${node.id}`)
        .when(isDataWarehouseNode, (node) => node.name || node.table_name)
        .otherwise(() => 'Unknown')

const getMathLabel = (math: string | undefined): string => {
    if (!math) {
        return 'Total count'
    }
    return match(math)
        .with('total', () => 'Total count')
        .with('dau', () => 'Unique users')
        .with('sum', () => 'Sum')
        .with('avg', () => 'Average')
        .with('min', () => 'Minimum')
        .with('max', () => 'Maximum')
        .with('unique_session', () => 'Unique sessions')
        .with('unique_group', () => 'Unique groups')
        .with('hogql', () => 'HogQL')
        .otherwise(() => math)
}

export type MetricEventDetailsProps = {
    metric: ExperimentMetric
}

export const MetricEventDetails = ({ metric }: MetricEventDetailsProps): JSX.Element =>
    match(metric)
        .when(isExperimentFunnelMetric, (funnelMetric: ExperimentFunnelMetric) => {
            const steps = funnelMetric.series.slice(0, 3)
            const hasMore = funnelMetric.series.length > 3

            return (
                <div className="flex items-center gap-1 flex-wrap text-xs text-muted">
                    {steps.map((step, index) => (
                        <div key={index} className="flex items-center gap-1">
                            {index > 0 && <IconArrowRight className="text-muted flex-shrink-0" fontSize="14" />}
                            <span className="truncate max-w-[150px]">{getSourceName(step)}</span>
                        </div>
                    ))}
                    {hasMore && (
                        <Tooltip title={funnelMetric.series.slice(3).map(getSourceName).join(', ')}>
                            <span className="text-muted">... +{funnelMetric.series.length - 3} more</span>
                        </Tooltip>
                    )}
                </div>
            )
        })
        .when(isExperimentMeanMetric, (meanMetric: ExperimentMeanMetric) => {
            const sourceName = getSourceName(meanMetric.source)
            const mathLabel = getMathLabel(meanMetric.source.math)

            return (
                <div className="text-xs text-muted">
                    <span className="truncate">{sourceName}</span>
                    <span className="text-muted"> ({mathLabel})</span>
                </div>
            )
        })
        .when(isExperimentRatioMetric, (ratioMetric: ExperimentRatioMetric) => {
            const numeratorName = getSourceName(ratioMetric.numerator)
            const denominatorName = getSourceName(ratioMetric.denominator)
            const numeratorMath = getMathLabel(ratioMetric.numerator.math)
            const denominatorMath = getMathLabel(ratioMetric.denominator.math)

            return (
                <div className="text-xs text-muted">
                    <div className="flex items-center gap-1">
                        <span className="font-semibold text-default">Numerator:</span>
                        <span className="truncate">{numeratorName}</span>
                        <span className="text-muted">({numeratorMath})</span>
                    </div>
                    <div className="flex items-center gap-1">
                        <span className="font-semibold text-default">Denominator:</span>
                        <span className="truncate">{denominatorName}</span>
                        <span className="text-muted">({denominatorMath})</span>
                    </div>
                </div>
            )
        })
        .otherwise(() => <div>Unknown metric type</div>)
