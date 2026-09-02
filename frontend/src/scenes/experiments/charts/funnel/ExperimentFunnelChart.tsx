import { useMemo } from 'react'

import {
    FunnelChart,
    type FunnelStepClickData,
    RATE_TO_PERCENT,
    type Series,
    funnelConversionRate,
} from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'
import { LemonCard } from 'lib/lemon-ui/LemonCard'

import {
    ExperimentFunnelMetric,
    ExperimentFunnelMetricStep,
    ExperimentQuery,
    NewExperimentQueryResponse,
    NodeKind,
} from '~/queries/schema/schema-general'
import { getExperimentVariants, getVariantColor } from '~/scenes/experiments/utils'
import { Experiment, StepOrderValue } from '~/types'

import { openExperimentPersonsModal } from './experimentPersonsModal'
import { FunnelTooltip } from './FunnelTooltip'
import { StepFooterCell } from './StepFooterCell'
import type { VariantFunnelMeta } from './types'

/** Step label at index 0 — the frontend-only step that precedes the backend's step numbering. */
const EXPOSURE_STEP_LABEL = 'Experiment exposure'

/** Floor for the plot region so a tall step footer can't squeeze the bars out of the chart. */
const MIN_PLOT_HEIGHT = 200

/** Target width of one step's bars. Steps cluster at this width instead of stretching to fill the
 *  container, and shrink below it once the funnel is too wide to fit. */
const STEP_BAND_WIDTH = 192

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
            EXPOSURE_STEP_LABEL,
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

    const stepTotals = useMemo(
        () => steps.map((_, stepIndex) => series.reduce((sum, s) => sum + (s.meta?.counts[stepIndex] ?? 0), 0)),
        [steps, series]
    )

    const config = useMemo(
        () => ({
            chartMinHeight: MIN_PLOT_HEIGHT,
            maxBandRange: steps.length * STEP_BAND_WIDTH,
            // Cursor-anchored like the insights funnel, instead of the funnel default pinned to the band top.
            tooltip: { placement: 'cursor' as const },
        }),
        [steps.length]
    )

    const handleStepClick = ({
        stepIndex,
        converted,
        series: clicked,
    }: FunnelStepClickData<VariantFunnelMeta>): void => {
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
    }

    return (
        <LemonCard hoverEffect={false} className="h-96 flex flex-col p-2">
            <FunnelChart<VariantFunnelMeta>
                steps={steps}
                series={series}
                theme={theme}
                config={config}
                tooltip={(ctx) => <FunnelTooltip ctx={ctx} steps={steps} showClickHint={!!experimentQuery} />}
                onStepClick={experimentQuery ? handleStepClick : undefined}
                stepFooter={(stepIndex) => (
                    <StepFooterCell stepIndex={stepIndex} steps={steps} stepTotals={stepTotals} />
                )}
                dataAttr="experiment-funnel-chart"
            />
        </LemonCard>
    )
}
