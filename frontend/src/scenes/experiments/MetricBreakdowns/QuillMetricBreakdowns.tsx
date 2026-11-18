import {
    Chip,
    ChipClose,
    Select,
    SelectContent,
    SelectGroup,
    SelectGroupLabel,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Text,
} from '@posthog/quill'

import { PROPERTY_FILTER_TYPE_TO_TAXONOMIC_FILTER_GROUP_TYPE } from 'lib/components/PropertyFilters/utils'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { extractDisplayLabel } from '~/queries/nodes/DataTable/utils'
import { ExperimentFunnelMetric, ExperimentMetric, isExperimentFunnelMetric } from '~/queries/schema/schema-general'
import { BreakdownAttributionType, StepOrderValue } from '~/types'

import { FUNNEL_STEP_COUNT_LIMIT } from 'products/product_analytics/frontend/insights/funnels/editor/FunnelsQuerySteps'

import { QuillHelpTooltip } from '../ExperimentView/QuillCardParts'
import {
    BreakdownAttributionHelp,
    breakdownAttributionValue,
    parseBreakdownAttribution,
} from './MetricBreakdownAttribution'
import { BREAKDOWN_LIMIT_HELP, breakdownLimitOptions } from './MetricBreakdownLimit'

const ATTRIBUTION_LABELS: Record<string, string> = {
    [BreakdownAttributionType.FirstTouch]: 'First touchpoint',
    [BreakdownAttributionType.LastTouch]: 'Last touchpoint',
    [BreakdownAttributionType.AllSteps]: 'All steps',
    [BreakdownAttributionType.Step]: 'Any step',
}

function attributionLabel(value: string): string {
    const [type, step] = value.split('/')
    return step !== undefined ? `Step ${parseInt(step) + 1}` : (ATTRIBUTION_LABELS[type] ?? value)
}

export function QuillMetricBreakdowns({
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
    const metricEventBreakdownsEnabled = useFeatureFlag('EXPERIMENT_METRIC_EVENT_BREAKDOWNS')
    const showAttribution = metricEventBreakdownsEnabled && isExperimentFunnelMetric(metric)
    const { breakdownLimit, options: limitOptions } = breakdownLimitOptions(metric)

    return (
        <div className="flex flex-wrap items-center gap-3">
            <div className="flex flex-wrap items-center gap-1">
                <Text size="xs" variant="muted" render={<span />}>
                    Breakdown by
                </Text>
                {metric.breakdownFilter?.breakdowns?.map((breakdown, index) => (
                    <Chip key={index} data-attr="experiment-breakdown-tag">
                        <span className="truncate">
                            <PropertyKeyInfo
                                value={extractDisplayLabel(String(breakdown.property))}
                                type={PROPERTY_FILTER_TYPE_TO_TAXONOMIC_FILTER_GROUP_TYPE[breakdown.type || 'event']}
                                disableIcon
                            />
                        </span>
                        <ChipClose onClick={() => onRemoveBreakdown(index)} aria-label="Remove breakdown" />
                    </Chip>
                ))}
            </div>
            {showAttribution && (
                <AttributionSelect metric={metric as ExperimentFunnelMetric} onChange={onAttributionChange} />
            )}
            {metricEventBreakdownsEnabled && (
                <div className="flex items-center gap-1">
                    <Text size="xs" variant="muted" render={<span />}>
                        Limit
                    </Text>
                    <QuillHelpTooltip label="breakdown limit" help={BREAKDOWN_LIMIT_HELP} />
                    <Select
                        value={String(breakdownLimit)}
                        onValueChange={(value) => {
                            const next = Number(value)
                            if (next && next !== breakdownLimit) {
                                onBreakdownLimitChange(next)
                            }
                        }}
                    >
                        <SelectTrigger size="sm" data-attr="experiment-breakdown-limit">
                            <SelectValue>
                                {(value: string) =>
                                    limitOptions.find((option) => String(option.value) === value)?.label ?? value
                                }
                            </SelectValue>
                        </SelectTrigger>
                        <SelectContent>
                            {limitOptions.map((option) => (
                                <SelectItem key={option.value} value={String(option.value)}>
                                    {option.label}
                                </SelectItem>
                            ))}
                        </SelectContent>
                    </Select>
                </div>
            )}
        </div>
    )
}

function AttributionSelect({
    metric,
    onChange,
}: {
    metric: ExperimentFunnelMetric
    onChange: (attributionType: BreakdownAttributionType, attributionValue?: number) => void
}): JSX.Element {
    const unordered = metric.funnel_order_type === StepOrderValue.UNORDERED
    const stepCount = metric.series?.length || 0
    const current = breakdownAttributionValue(metric)

    return (
        <div className="flex items-center gap-1">
            <Text size="xs" variant="muted" render={<span />}>
                Attribution
            </Text>
            <QuillHelpTooltip label="attribution" help={<BreakdownAttributionHelp unordered={unordered} />} />
            <Select
                value={current as string}
                onValueChange={(value) => {
                    if (typeof value === 'string' && value) {
                        onChange(...parseBreakdownAttribution(value))
                    }
                }}
            >
                <SelectTrigger size="sm" data-attr="experiment-breakdown-attribution">
                    <SelectValue>{(value: string) => attributionLabel(value)}</SelectValue>
                </SelectTrigger>
                <SelectContent>
                    <SelectItem value={BreakdownAttributionType.FirstTouch}>First touchpoint</SelectItem>
                    <SelectItem value={BreakdownAttributionType.LastTouch}>Last touchpoint</SelectItem>
                    <SelectItem value={BreakdownAttributionType.AllSteps}>All steps</SelectItem>
                    {unordered ? (
                        <SelectItem value={BreakdownAttributionType.Step}>Any step</SelectItem>
                    ) : (
                        <SelectGroup>
                            <SelectGroupLabel>Specific step</SelectGroupLabel>
                            {Array.from({ length: FUNNEL_STEP_COUNT_LIMIT }, (_, stepIndex) => stepIndex)
                                .filter(
                                    (stepIndex) =>
                                        stepIndex < stepCount || stepIndex === metric.breakdownAttributionValue
                                )
                                .map((stepIndex) => (
                                    <SelectItem key={stepIndex} value={`${BreakdownAttributionType.Step}/${stepIndex}`}>
                                        Step {stepIndex + 1}
                                    </SelectItem>
                                ))}
                        </SelectGroup>
                    )}
                </SelectContent>
            </Select>
        </div>
    )
}
