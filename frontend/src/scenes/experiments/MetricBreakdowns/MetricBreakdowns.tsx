import { IconInfo } from '@posthog/icons'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { BreakdownTag } from 'scenes/insights/filters/BreakdownFilter/BreakdownTag'

import { ExperimentFunnelMetric, ExperimentMetric } from '~/queries/schema/schema-general'
import { isExperimentFunnelMetric } from '~/queries/schema/schema-general'
import { BreakdownAttributionType, StepOrderValue } from '~/types'

import { MetricBreakdownAttribution } from './MetricBreakdownAttribution'
import { MetricBreakdownLimit } from './MetricBreakdownLimit'

/**
 * Renders the metric's breakdown chips on the left, then (behind the
 * metric-event-breakdowns flag) the funnel attribution dropdown and the
 * breakdown limit. Attribution is funnel-only; the limit applies to all types.
 */
export function MetricBreakdowns({
    metric,
    onRemoveBreakdown,
    onAttributionChange,
    onBreakdownLimitChange,
}: {
    metric: ExperimentMetric
    onRemoveBreakdown: (index: number) => void
    onAttributionChange: (attributionType: BreakdownAttributionType, attributionValue?: number) => void
    onBreakdownLimitChange: (breakdownLimit: number) => void
}): JSX.Element {
    /**
     * on the frontend, this flag controls whether we show the attribution and limit settings.
     * these settings are available only for funnels
     */
    const metricEventBreakdownsEnabled = useFeatureFlag('EXPERIMENT_METRIC_EVENT_BREAKDOWNS')

    /**
     * this should collapse into isExperimentFunnelMetric(metric) once enabled
     */
    const showAttribution = metricEventBreakdownsEnabled && isExperimentFunnelMetric(metric)
    /**
     * all metric tipes will have a breakdown limit
     */
    const showLimit = metricEventBreakdownsEnabled

    return (
        <div className="flex items-center gap-3">
            <div className="flex items-center gap-2">
                {metric.breakdownFilter?.breakdowns?.map((breakdown, index) => (
                    <BreakdownTag
                        key={index}
                        breakdown={breakdown.property}
                        breakdownType={breakdown.type || 'event'}
                        onClose={() => onRemoveBreakdown(index)}
                        size="small"
                    />
                ))}
            </div>
            {showAttribution && (
                <div className="flex items-center gap-1">
                    <span className="text-muted">Attribution</span>
                    <Tooltip
                        title={
                            <>
                                Which funnel step the breakdown value is read from for each user:
                                <ul className="list-disc pl-4">
                                    <li>
                                        <strong>First touchpoint</strong>: the first property value seen in any step
                                    </li>
                                    <li>
                                        <strong>Last touchpoint</strong>: the last property value seen across all steps
                                    </li>
                                    <li>
                                        <strong>All steps</strong>: The property value must appear on all steps
                                    </li>
                                    {(metric as ExperimentFunnelMetric).funnel_order_type ===
                                    StepOrderValue.UNORDERED ? (
                                        <li>
                                            <strong>Any step</strong>: value at any matching step
                                        </li>
                                    ) : (
                                        <li>
                                            <strong>Specific step</strong>: value at a step you choose
                                        </li>
                                    )}
                                </ul>
                            </>
                        }
                    >
                        <IconInfo className="text-secondary text-base shrink-0" />
                    </Tooltip>
                    <MetricBreakdownAttribution
                        metric={metric as ExperimentFunnelMetric}
                        onChange={onAttributionChange}
                    />
                </div>
            )}
            {showLimit && <MetricBreakdownLimit metric={metric} onChange={onBreakdownLimitChange} />}
        </div>
    )
}
