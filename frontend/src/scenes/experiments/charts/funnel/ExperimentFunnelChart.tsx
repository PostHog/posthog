import { useCallback, useMemo, useState } from 'react'

import {
    FunnelChart,
    type FunnelStepClickData,
    RATE_TO_PERCENT,
    type Series,
    type TooltipContext,
    TooltipSurface,
    TooltipSwatch,
    funnelConversionRate,
} from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'
import { IconTrendingFlat, IconTrendingFlatDown } from 'lib/lemon-ui/icons'
import { Lettermark, LettermarkColor } from 'lib/lemon-ui/Lettermark'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { humanFriendlyNumber, percentage } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'
import { funnelTitle } from 'scenes/trends/persons-modal/persons-modal-utils'
import { openPersonsModal } from 'scenes/trends/persons-modal/PersonsModal'

import {
    ExperimentActorsQuery,
    ExperimentFunnelMetric,
    ExperimentFunnelMetricStep,
    ExperimentQuery,
    NewExperimentQueryResponse,
    NodeKind,
} from '~/queries/schema/schema-general'
import { EXPOSURE_DEFAULT_EVENT } from '~/scenes/experiments/exposureContract'
import { getExperimentVariants, getVariantColor } from '~/scenes/experiments/utils'
import { Experiment, StepOrderValue } from '~/types'

interface VariantFunnelMeta {
    variantKey: string
    /** Absolute converted count per step; index 0 is the exposure count. */
    counts: number[]
}

export interface ExperimentFunnelChartProps {
    result: NewExperimentQueryResponse
    experiment: Experiment
    metric: ExperimentFunnelMetric
    /** Enables click-to-inspect actors on the funnel bars. */
    experimentQuery?: ExperimentQuery
}

function getStepName(step: ExperimentFunnelMetricStep | undefined, stepNumber: number): string {
    if (step?.kind === NodeKind.EventsNode) {
        return step.custom_name || step.name || step.event || `Step ${stepNumber}`
    }
    if (step?.kind === NodeKind.ActionsNode) {
        return step.custom_name || step.name || `Action ${step.id}`
    }
    if (step?.kind === NodeKind.ExperimentDataWarehouseNode) {
        return step.custom_name || step.name || step.table_name || `Step ${stepNumber}`
    }
    return `Step ${stepNumber}`
}

/**
 * Opens the persons modal for a funnel step. The frontend prepends an "Experiment exposure"
 * step at index 0 that the backend actors funnel doesn't have, so frontend step index N maps
 * to backend step number N. The exposure step itself can't be queried, and neither can
 * drop-offs at the first metric step ("exposed but never entered the funnel").
 */
function openExperimentPersonsModal({
    stepIndex,
    stepName,
    converted,
    variantKey,
    orderType,
    experimentQuery,
    experiment,
}: {
    stepIndex: number
    stepName: string
    converted: boolean
    variantKey: string
    orderType?: StepOrderValue
    experimentQuery: ExperimentQuery
    experiment: Experiment
}): void {
    const backendStepNo = stepIndex
    if (backendStepNo < 1 || (!converted && backendStepNo === 1)) {
        return
    }

    const query: ExperimentActorsQuery = {
        kind: NodeKind.ExperimentActorsQuery,
        source: experimentQuery,
        funnelStep: converted ? backendStepNo : -backendStepNo,
        funnelStepBreakdown: variantKey,
        includeRecordings: true,
        exposureConfig: experiment.exposure_criteria?.exposure_config || {
            kind: NodeKind.ExperimentEventExposureConfig,
            event: EXPOSURE_DEFAULT_EVENT,
            properties: [],
        },
        multipleVariantHandling: experiment.exposure_criteria?.multiple_variant_handling || 'exclude',
        featureFlagKey: experiment.feature_flag?.key || '',
    }

    openPersonsModal({
        title: funnelTitle({
            converted,
            step: stepIndex + 1,
            breakdown_value: variantKey,
            label: stepName,
            order_type: orderType,
        }),
        query,
        additionalSelect: { matched_recordings: 'matched_recordings' },
    })
}

function TooltipRow({ label, value }: { label: string; value: React.ReactNode }): JSX.Element {
    return (
        <div className="flex items-center justify-between gap-4">
            <span className="opacity-60">{label}</span>
            <strong className="tabular-nums">{value}</strong>
        </div>
    )
}

function StepFooterCell({
    stepIndex,
    label,
    count,
    basisCount,
    previousCount,
}: {
    stepIndex: number
    label: string
    count: number
    basisCount: number
    previousCount: number | null
}): JSX.Element {
    const droppedOff = previousCount != null ? Math.max(previousCount - count, 0) : 0
    return (
        <div className="flex flex-col gap-1 px-1 py-2 text-xs">
            <div className="flex items-center gap-1.5 font-medium">
                <Lettermark name={stepIndex + 1} color={LettermarkColor.Gray} />
                <span className="truncate" title={label}>
                    {label}
                </span>
            </div>
            <Tooltip title="Users who completed this step, with conversion rate relative to the first step">
                <div className="flex items-center gap-1.5">
                    <IconTrendingFlat className="text-success shrink-0" />
                    <span>
                        {pluralize(count, 'user')}{' '}
                        <span className="text-secondary">
                            ({percentage(funnelConversionRate(count, basisCount), 2)})
                        </span>
                    </span>
                </div>
            </Tooltip>
            {previousCount != null && (
                <Tooltip title="Users who didn't complete this step, with drop-off rate relative to the previous step">
                    <div className="flex items-center gap-1.5">
                        <IconTrendingFlatDown className="text-danger shrink-0" />
                        <span>
                            {pluralize(droppedOff, 'user')}{' '}
                            <span className="text-secondary">
                                ({percentage(1 - funnelConversionRate(count, previousCount), 2)})
                            </span>
                        </span>
                    </div>
                </Tooltip>
            )}
        </div>
    )
}

/** Experiment funnel metric results as a quill-charts funnel — one band per step, one bar per variant. */
export function ExperimentFunnelChart({
    result,
    experiment,
    metric,
    experimentQuery,
}: ExperimentFunnelChartProps): JSX.Element {
    const theme = useChartTheme()

    const variants = useMemo(
        () => [result.baseline, ...(result.variant_results ?? [])].filter(Boolean),
        [result.baseline, result.variant_results]
    )

    const numMetricSteps = Math.max(metric.series.length, ...variants.map((v) => v.step_counts?.length ?? 0))

    const steps = useMemo(() => {
        const isUnordered = metric.funnel_order_type === StepOrderValue.UNORDERED
        return [
            'Experiment exposure',
            ...Array.from({ length: numMetricSteps }, (_, i) =>
                isUnordered ? `Completed ${i + 1} ${i === 0 ? 'step' : 'steps'}` : getStepName(metric.series[i], i + 1)
            ),
        ]
    }, [metric.funnel_order_type, metric.series, numMetricSteps])

    const series = useMemo<Series<VariantFunnelMeta>[]>(() => {
        const flagVariants = getExperimentVariants(experiment)
        return variants.map((variant) => {
            const counts = [
                variant.number_of_samples,
                ...Array.from({ length: numMetricSteps }, (_, i) => variant.step_counts?.[i] ?? 0),
            ]
            return {
                key: variant.key,
                label: variant.key,
                color: getVariantColor(variant.key, flagVariants),
                data: counts.map((count) => funnelConversionRate(count, counts[0]) * RATE_TO_PERCENT),
                meta: { variantKey: variant.key, counts },
            }
        })
    }, [variants, experiment, numMetricSteps])

    // The chart owns an interactive legend that hides toggled-off variants from the bars, axes, and
    // tooltip. Control that state here so the per-step footer totals below only sum the variants
    // currently drawn, instead of drifting to a stale all-variants aggregate.
    const [hiddenKeys, setHiddenKeys] = useState<string[]>([])
    const onToggleSeries = useCallback((key: string, hidden: boolean): void => {
        setHiddenKeys((prev) => (hidden ? [...prev, key] : prev.filter((k) => k !== key)))
    }, [])

    const stepTotals = useMemo(
        () =>
            steps.map((_, stepIndex) =>
                series.reduce(
                    (sum, s) => sum + (hiddenKeys.includes(s.key) ? 0 : (s.meta?.counts[stepIndex] ?? 0)),
                    0
                )
            ),
        [steps, series, hiddenKeys]
    )

    const renderTooltip = useCallback(
        (ctx: TooltipContext<VariantFunnelMeta>): React.ReactNode => {
            const entry = ctx.seriesData.find((e) => e.series.key === ctx.hoveredSeriesKey) ?? ctx.seriesData[0]
            const meta = entry?.series.meta
            if (!entry || !meta) {
                return null
            }
            const stepIndex = ctx.dataIndex
            const count = meta.counts[stepIndex] ?? 0
            const previous = stepIndex > 0 ? (meta.counts[stepIndex - 1] ?? 0) : null
            return (
                <TooltipSurface>
                    <div className="flex items-center gap-2 font-semibold mb-1">
                        <TooltipSwatch color={entry.color} />
                        <span className="truncate">
                            {steps[stepIndex]} · {meta.variantKey}
                        </span>
                    </div>
                    <TooltipRow label={stepIndex === 0 ? 'Entered' : 'Converted'} value={humanFriendlyNumber(count)} />
                    {previous != null && (
                        <>
                            <TooltipRow
                                label="Dropped off"
                                value={humanFriendlyNumber(Math.max(previous - count, 0))}
                            />
                            <TooltipRow
                                label="Conversion so far"
                                value={percentage(funnelConversionRate(count, meta.counts[0] ?? 0), 2, true)}
                            />
                            <TooltipRow
                                label="Conversion from previous"
                                value={percentage(funnelConversionRate(count, previous), 2, true)}
                            />
                        </>
                    )}
                    {!!experimentQuery && stepIndex > 0 && (
                        <div className="mt-1 pt-1 border-t border-current/25 text-xs opacity-60 text-center">
                            Click to view users
                        </div>
                    )}
                </TooltipSurface>
            )
        },
        [steps, experimentQuery]
    )

    const config = useMemo(
        () => ({ legend: { show: series.length > 1, hiddenKeys, onToggleSeries } }),
        [series.length, hiddenKeys, onToggleSeries]
    )

    const renderStepFooter = useCallback(
        (stepIndex: number): React.ReactNode => (
            <StepFooterCell
                stepIndex={stepIndex}
                label={steps[stepIndex]}
                count={stepTotals[stepIndex]}
                basisCount={stepTotals[0]}
                previousCount={stepIndex > 0 ? stepTotals[stepIndex - 1] : null}
            />
        ),
        [steps, stepTotals]
    )

    const handleStepClick = useCallback(
        ({ stepIndex, converted, series: clicked }: FunnelStepClickData<VariantFunnelMeta>): void => {
            if (!experimentQuery || !clicked.meta) {
                return
            }
            openExperimentPersonsModal({
                stepIndex,
                stepName: steps[stepIndex],
                converted,
                variantKey: clicked.meta.variantKey,
                orderType: metric.funnel_order_type,
                experimentQuery,
                experiment,
            })
        },
        [experimentQuery, experiment, steps, metric.funnel_order_type]
    )

    return (
        <div className="h-96">
            <FunnelChart<VariantFunnelMeta>
                steps={steps}
                series={series}
                theme={theme}
                config={config}
                tooltip={renderTooltip}
                onStepClick={experimentQuery ? handleStepClick : undefined}
                stepFooter={renderStepFooter}
                dataAttr="experiment-funnel-chart"
            />
        </div>
    )
}
