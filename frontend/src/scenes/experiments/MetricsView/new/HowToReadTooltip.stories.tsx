import './MetricRowGroup.scss'

import type { Meta, StoryObj } from '@storybook/react'
import { useActions } from 'kea'
import { useEffect } from 'react'

import { IconTrending } from '@posthog/icons'

import { getSeriesColor } from 'lib/colors'
import { IconTrendingDown } from 'lib/lemon-ui/icons'
import { humanFriendlyLargeNumber } from 'lib/utils/numbers'

import type {
    ExperimentMetric,
    ExperimentStatsBaseValidated,
    ExperimentVariantResultBayesian,
    ExperimentVariantResultFrequentist,
} from '~/queries/schema/schema-general'
import { ExperimentMetricType, NodeKind } from '~/queries/schema/schema-general'
import { useChartColors } from '~/scenes/experiments/MetricsView/shared/colors'
import { FIXED_HEIGHT_STYLE } from '~/scenes/experiments/MetricsView/shared/rowHeights'
import {
    type ExperimentVariantResult,
    formatDeltaPercent,
    formatMetricValue,
    getMetricSubtitleValues,
    getVariantInterval,
    isDeltaPositive,
    isSignificant,
    isWinning,
} from '~/scenes/experiments/MetricsView/shared/utils'
import { ExperimentStatsMethod } from '~/types'

import { experimentLogic } from '../../experimentLogic'
import { ChartCell } from './ChartCell'
import { SIGNIFICANT_ROW_BG_ALPHA } from './constants'
import { HowToReadTooltip } from './HowToReadTooltip'

/**
 * Narrow renders of the metric row for the "How to read" tooltip screenshots.
 * They reuse the exact cell markup, formatters, and ChartCell from MetricRowGroup
 * so the captured images stay pixel-faithful to the results table.
 */

const EXAMPLE_METRIC = {
    kind: NodeKind.ExperimentMetric,
    uuid: 'how-to-read-example',
    metric_type: ExperimentMetricType.RATIO,
    numerator: { kind: NodeKind.EventsNode, event: 'purchase' },
    denominator: { kind: NodeKind.EventsNode, event: '$pageview' },
} as ExperimentMetric

const BASELINE: ExperimentStatsBaseValidated = {
    key: 'control',
    number_of_samples: 800,
    sum: 424,
    sum_squares: 424,
    denominator_sum: 800,
    denominator_sum_squares: 800,
}

// Interval midpoints produce the delta shown in the Delta column: +8.63% and -10.47%
const FREQUENTIST_WINNING: ExperimentVariantResultFrequentist = {
    method: 'frequentist',
    key: 'test-1',
    number_of_samples: 800,
    sum: 456,
    sum_squares: 456,
    denominator_sum: 800,
    denominator_sum_squares: 800,
    significant: true,
    p_value: 0.003,
    confidence_interval: [0.0313, 0.1413],
}

const FREQUENTIST_LOSING: ExperimentVariantResultFrequentist = {
    method: 'frequentist',
    key: 'test-2',
    number_of_samples: 800,
    sum: 376,
    sum_squares: 376,
    denominator_sum: 800,
    denominator_sum_squares: 800,
    significant: true,
    p_value: 0.008,
    confidence_interval: [-0.1597, -0.0497],
}

const FREQUENTIST_NOT_SIGNIFICANT: ExperimentVariantResultFrequentist = {
    method: 'frequentist',
    key: 'test-2',
    number_of_samples: 800,
    sum: 432,
    sum_squares: 432,
    denominator_sum: 800,
    denominator_sum_squares: 800,
    significant: false,
    p_value: 0.34,
    confidence_interval: [-0.0497, 0.0913],
}

const toBayesian = (result: ExperimentVariantResultFrequentist): ExperimentVariantResultBayesian => ({
    key: result.key,
    number_of_samples: result.number_of_samples,
    sum: result.sum,
    sum_squares: result.sum_squares,
    denominator_sum: result.denominator_sum,
    denominator_sum_squares: result.denominator_sum_squares,
    method: 'bayesian',
    significant: result.significant,
    chance_to_win: result.significant ? (result.confidence_interval![0] > 0 ? 0.98 : 0.02) : 0.72,
    credible_interval: result.confidence_interval,
})

function VariantLabel({ variantKey, index }: { variantKey: string; index: number }): JSX.Element {
    return (
        <span className="flex items-center min-w-0">
            <div
                className="w-2 h-2 rounded-full shrink-0"
                // eslint-disable-next-line react/forbid-dom-props
                style={{ backgroundColor: getSeriesColor(index) }}
            />
            <span className="ml-2 text-xs font-semibold truncate text-secondary">{variantKey}</span>
        </span>
    )
}

function SignificanceExample(): JSX.Element {
    const colors = useChartColors()
    const rows: { result: ExperimentStatsBaseValidated | ExperimentVariantResult; isBaseline: boolean }[] = [
        { result: BASELINE, isBaseline: true },
        { result: FREQUENTIST_WINNING, isBaseline: false },
        { result: FREQUENTIST_LOSING, isBaseline: false },
    ]

    return (
        <table className="w-[340px]">
            <tbody>
                {rows.map(({ result, isBaseline }, index) => {
                    const variantResult = isBaseline ? null : (result as ExperimentVariantResult)
                    const significant = variantResult ? isSignificant(variantResult) : false
                    const winning = variantResult ? isWinning(variantResult, EXAMPLE_METRIC.goal) : undefined
                    const deltaPositive = variantResult ? isDeltaPositive(variantResult) : undefined
                    const rowBackgroundColor = significant
                        ? winning
                            ? `${colors.BAR_POSITIVE}${SIGNIFICANT_ROW_BG_ALPHA}`
                            : `${colors.BAR_NEGATIVE}${SIGNIFICANT_ROW_BG_ALPHA}`
                        : undefined
                    const rowBackgroundImage = rowBackgroundColor
                        ? `linear-gradient(${rowBackgroundColor}, ${rowBackgroundColor})`
                        : undefined
                    const { numerator, denominator } = getMetricSubtitleValues(result, EXAMPLE_METRIC)
                    const cellClass = 'pt-1 pl-3 pr-3 pb-1 whitespace-nowrap overflow-hidden bg-bg-light'
                    const cellStyle = { ...FIXED_HEIGHT_STYLE, backgroundImage: rowBackgroundImage }

                    return (
                        <tr key={result.key} style={FIXED_HEIGHT_STYLE}>
                            <td
                                className={`w-20 ${cellClass}`}
                                // eslint-disable-next-line react/forbid-dom-props
                                style={cellStyle}
                            >
                                <VariantLabel variantKey={result.key} index={index} />
                            </td>
                            <td
                                className={`w-24 text-left ${cellClass}`}
                                // eslint-disable-next-line react/forbid-dom-props
                                style={cellStyle}
                            >
                                <div className="metric-cell">
                                    <div>{formatMetricValue(result, EXAMPLE_METRIC)}</div>
                                    <div className="text-xs text-muted">
                                        {humanFriendlyLargeNumber(numerator)} / {humanFriendlyLargeNumber(denominator)}
                                    </div>
                                </div>
                            </td>
                            <td
                                className={`text-left ${cellClass}`}
                                // eslint-disable-next-line react/forbid-dom-props
                                style={cellStyle}
                            >
                                {variantResult && (
                                    <div className="flex items-center gap-1">
                                        <span
                                            className={`metric-cell font-bold ${significant ? (winning ? 'text-success' : 'text-danger') : ''}`}
                                        >
                                            {formatDeltaPercent(variantResult)}
                                        </span>
                                        {significant && deltaPositive !== undefined && (
                                            <span className={`shrink-0 ${winning ? 'text-success' : 'text-danger'}`}>
                                                {deltaPositive ? (
                                                    <IconTrending
                                                        className="w-5 h-5"
                                                        // eslint-disable-next-line react/forbid-dom-props
                                                        style={{ strokeWidth: 2.5 }}
                                                    />
                                                ) : (
                                                    <IconTrendingDown
                                                        className="w-5 h-5"
                                                        // eslint-disable-next-line react/forbid-dom-props
                                                        style={{ strokeWidth: 2.5 }}
                                                    />
                                                )}
                                            </span>
                                        )}
                                    </div>
                                )}
                            </td>
                        </tr>
                    )
                })}
            </tbody>
        </table>
    )
}

function IntervalsExample({ results }: { results: ExperimentVariantResult[] }): JSX.Element {
    // Mirrors MetricsTable's shared-axis computation over the displayed results
    const maxAbsValue = Math.max(
        ...results.flatMap((result) => (getVariantInterval(result) ?? []).map((bound) => Math.abs(bound)))
    )
    const axisRange = maxAbsValue + Math.max(maxAbsValue * 0.05, 0.1)

    return (
        <table className="w-[340px]">
            <tbody>
                {results.map((result, index) => (
                    <tr key={result.key} style={FIXED_HEIGHT_STYLE}>
                        <ChartCell
                            variantResult={result}
                            metric={EXAMPLE_METRIC}
                            axisRange={axisRange}
                            metricUuid={`how-to-read-${index}`}
                        />
                    </tr>
                ))}
            </tbody>
        </table>
    )
}

const meta: Meta = {
    title: 'Experiments/HowToReadTooltip',
    component: HowToReadTooltip,
    parameters: {
        layout: 'centered',
        testOptions: { snapshotBrowsers: ['chromium'] },
    },
}
export default meta

type Story = StoryObj

function TooltipPreview({ statsMethod }: { statsMethod: ExperimentStatsMethod }): JSX.Element {
    const { setExperiment } = useActions(experimentLogic)
    useEffect(() => {
        setExperiment({ stats_config: { method: statsMethod } })
    }, [setExperiment, statsMethod])

    return (
        <div className="flex justify-center p-8">
            <HowToReadTooltip visible />
        </div>
    )
}

export const TooltipBayesian: Story = {
    render: () => <TooltipPreview statsMethod={ExperimentStatsMethod.Bayesian} />,
}

export const TooltipFrequentist: Story = {
    render: () => <TooltipPreview statsMethod={ExperimentStatsMethod.Frequentist} />,
}

export const Significance: Story = {
    render: () => <SignificanceExample />,
}

export const IntervalsFrequentist: Story = {
    render: () => <IntervalsExample results={[FREQUENTIST_WINNING, FREQUENTIST_NOT_SIGNIFICANT]} />,
}

export const IntervalsBayesian: Story = {
    render: () => (
        <IntervalsExample results={[toBayesian(FREQUENTIST_WINNING), toBayesian(FREQUENTIST_NOT_SIGNIFICANT)]} />
    ),
}
