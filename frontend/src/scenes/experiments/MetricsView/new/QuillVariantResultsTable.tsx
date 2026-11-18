import { useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconCursorClick, IconTrending } from '@posthog/icons'
import { Badge, DataTable, Text, Tooltip, TooltipContent, TooltipTrigger, cn } from '@posthog/quill'
import type { DataTableProps } from '@posthog/quill'

import { IconTrendingDown } from 'lib/lemon-ui/icons'
import { humanFriendlyLargeNumber, humanFriendlyNumber } from 'lib/utils/numbers'
import { teamLogic } from 'scenes/teamLogic'

import {
    ExperimentMetric,
    ExperimentStatsBaseValidated,
    isExperimentQuantileMetric,
} from '~/queries/schema/schema-general'
import { ExperimentStatsMethod } from '~/types'

import { QuillHelpTooltip } from '../../ExperimentView/QuillCardParts'
import { QuillVariantTag } from '../../ExperimentView/QuillVariantTag'
import { useSvgResizeObserver } from '../hooks/useSvgResizeObserver'
import { useChartColors } from '../shared/colors'
import {
    type ExperimentVariantResult,
    formatChanceToWinForGoal,
    formatDeltaPercent,
    formatIntervalPercent,
    formatMetricValue,
    formatPValue,
    formatQuantileLevel,
    getIntervalLabel,
    getMetricSubtitleValues,
    getNiceTickValues,
    isBayesianResult,
    isDeltaPositive,
    isSignificant,
    isWinning,
    metricSupportsTimeseries,
} from '../shared/utils'
import { VariantChart } from './ChartCell'
import {
    CHART_CELL_VIEW_BOX_HEIGHT,
    GRID_LINES_OPACITY,
    SVG_EDGE_MARGIN,
    TICK_FONT_SIZE,
    TICK_PANEL_HEIGHT,
    VIEW_BOX_WIDTH,
} from './constants'
import { GridLines } from './GridLines'
import { P_VALUE_HELP, P_VALUE_SEQUENTIAL_HELP, WIN_CHANCE_HELP } from './metricsTableCopy'
import { TickLabels } from './TickLabels'
import { useAxisScale } from './useAxisScale'

export type VariantRow =
    | { variant: ExperimentStatsBaseValidated; isBaseline: true }
    | { variant: ExperimentVariantResult; isBaseline: false }

type VariantDataTable = DataTableProps<VariantRow, unknown>

function QuillAxisTicks({ axisRange }: { axisRange: number }): JSX.Element | null {
    const [svgWidth, setSvgWidth] = useState<number | undefined>(undefined)
    const tickValues = axisRange > 0 ? getNiceTickValues(axisRange) : []
    const scale = useAxisScale(axisRange || 0, VIEW_BOX_WIDTH, SVG_EDGE_MARGIN)
    const { ticksSvgRef } = useSvgResizeObserver([axisRange])

    useEffect(() => {
        const element = ticksSvgRef.current
        if (!element) {
            return
        }
        const updateWidth = (): void => setSvgWidth(element.getBoundingClientRect().width)
        updateWidth()
        window.addEventListener('resize', updateWidth)
        return () => window.removeEventListener('resize', updateWidth)
    }, [ticksSvgRef, axisRange])

    if (!axisRange) {
        return null
    }

    return (
        <svg
            ref={ticksSvgRef}
            viewBox={`0 0 ${VIEW_BOX_WIDTH} ${TICK_PANEL_HEIGHT + 10}`}
            preserveAspectRatio="xMidYMid meet"
            className="block w-full"
        >
            <TickLabels
                tickValues={tickValues}
                scale={scale}
                y={(TICK_PANEL_HEIGHT + 13) / 2}
                viewBoxWidth={VIEW_BOX_WIDTH}
                fontSize={TICK_FONT_SIZE}
                fontWeight="600"
                dominantBaseline="middle"
                svgWidth={svgWidth}
            />
        </svg>
    )
}

function BaselineGrid({ axisRange }: { axisRange: number }): JSX.Element {
    const colors = useChartColors()
    const scale = useAxisScale(axisRange, VIEW_BOX_WIDTH, SVG_EDGE_MARGIN)
    return (
        <svg
            viewBox={`0 0 ${VIEW_BOX_WIDTH} ${CHART_CELL_VIEW_BOX_HEIGHT}`}
            preserveAspectRatio="none"
            className="h-10 w-full"
        >
            <GridLines
                tickValues={getNiceTickValues(axisRange)}
                scale={scale}
                height={CHART_CELL_VIEW_BOX_HEIGHT}
                viewBoxWidth={VIEW_BOX_WIDTH}
                zeroLineColor={colors.ZERO_LINE}
                gridLineColor={colors.BOUNDARY_LINES}
                zeroLineWidth={1.25}
                gridLineWidth={0.75}
                opacity={GRID_LINES_OPACITY}
            />
        </svg>
    )
}

function SummaryRow({ label, children }: { label: string; children: React.ReactNode }): JSX.Element {
    return (
        <span className="flex items-center justify-between gap-6">
            <span className="opacity-70">{label}</span>
            <span className="font-semibold">{children}</span>
        </span>
    )
}

/** What the hover card of a variant's chart says, in quill. */
function QuillVariantSummary({
    variant,
    metric,
    isBaseline,
}: {
    variant: ExperimentVariantResult
    metric: ExperimentMetric
    isBaseline: boolean
}): JSX.Element {
    const { baseCurrency } = useValues(teamLogic)
    const significant = isSignificant(variant)
    const winning = isWinning(variant, metric.goal)

    return (
        <span className="flex min-w-56 flex-col gap-1">
            <span className="flex items-center justify-between gap-6">
                <span className="font-semibold">{variant.key}</span>
                {!isBaseline && (
                    <Badge variant={!significant ? 'default' : winning ? 'success' : 'destructive'}>
                        {!significant ? 'Not significant' : winning ? 'Won' : 'Lost'}
                    </Badge>
                )}
            </span>
            {isExperimentQuantileMetric(metric) ? (
                <>
                    <SummaryRow label={`${formatQuantileLevel(metric.quantile)}:`}>
                        {formatMetricValue(variant, metric, baseCurrency)}
                    </SummaryRow>
                    <SummaryRow label="Events:">
                        {variant.denominator_sum != null ? humanFriendlyNumber(variant.denominator_sum) : '—'}
                    </SummaryRow>
                </>
            ) : (
                <SummaryRow label="Total value:">
                    {variant.sum != null ? humanFriendlyNumber(variant.sum) : '—'}
                </SummaryRow>
            )}
            <SummaryRow label="Exposures:">
                {variant.number_of_samples != null ? humanFriendlyNumber(variant.number_of_samples) : '—'}
            </SummaryRow>
            {isBayesianResult(variant) ? (
                <SummaryRow label="Chance to win:">{formatChanceToWinForGoal(variant, metric.goal)}</SummaryRow>
            ) : (
                <SummaryRow label="p-value:">{formatPValue(variant.p_value)}</SummaryRow>
            )}
            <SummaryRow label="Delta:">{isBaseline ? 'Baseline' : formatDeltaPercent(variant)}</SummaryRow>
            <SummaryRow label={`${getIntervalLabel(variant)}:`}>{formatIntervalPercent(variant)}</SummaryRow>
            {metricSupportsTimeseries(metric) && !isBaseline && (
                <span className="mt-1 flex items-center justify-center gap-1 opacity-70">
                    <IconCursorClick />
                    Click to view timeseries
                </span>
            )}
        </span>
    )
}

function resultTone(variant: ExperimentVariantResult, metric: ExperimentMetric): 'success' | 'destructive' | null {
    if (!isSignificant(variant)) {
        return null
    }
    return isWinning(variant, metric.goal) ? 'success' : 'destructive'
}

export function winChanceHeader(statsMethod: ExperimentStatsMethod, sequentialTestingEnabled: boolean): JSX.Element {
    if (statsMethod === ExperimentStatsMethod.Frequentist) {
        return (
            <span className="inline-flex items-center gap-1">
                p-value
                <QuillHelpTooltip
                    label="p-value"
                    help={sequentialTestingEnabled ? P_VALUE_SEQUENTIAL_HELP : P_VALUE_HELP}
                />
            </span>
        )
    }
    return (
        <span className="inline-flex items-center gap-1">
            Win %
            <QuillHelpTooltip label="win chance" help={WIN_CHANCE_HELP} />
        </span>
    )
}

export function QuillVariantResultsTable({
    metric,
    rows,
    axisRange,
    isSecondary,
    statsMethod,
    sequentialTestingEnabled,
    onTimeseriesClick,
    variantActions,
    gradientSuffix,
}: {
    metric: ExperimentMetric
    rows: VariantRow[]
    axisRange: number
    isSecondary: boolean
    statsMethod: ExperimentStatsMethod
    sequentialTestingEnabled: boolean
    onTimeseriesClick?: (variant: ExperimentVariantResult) => void
    variantActions?: (row: VariantRow) => JSX.Element | null
    gradientSuffix?: string
}): JSX.Element {
    const { baseCurrency } = useValues(teamLogic)
    const timeseries = metricSupportsTimeseries(metric) ? onTimeseriesClick : undefined

    const columns: VariantDataTable['columns'] = [
        {
            id: 'variant',
            header: 'Variant',
            enableSorting: false,
            cell: ({ row: { original } }) => (
                <span className="flex min-w-32 items-center gap-1">
                    <QuillVariantTag variantKey={original.variant.key} />
                    {variantActions?.(original)}
                </span>
            ),
        },
        {
            id: 'value',
            header: 'Value',
            enableSorting: false,
            cell: ({ row: { original } }) => {
                const { numerator, denominator } = getMetricSubtitleValues(original.variant, metric)
                return (
                    <span className="flex min-w-24 flex-col whitespace-nowrap">
                        <Text size="xs" weight="medium" render={<span />}>
                            {formatMetricValue(original.variant, metric, baseCurrency)}
                        </Text>
                        <Text size="xxs" variant="muted" render={<span />}>
                            {humanFriendlyLargeNumber(numerator)} / {humanFriendlyLargeNumber(denominator)}
                        </Text>
                    </span>
                )
            },
        },
        {
            id: 'delta',
            header: 'Delta',
            enableSorting: false,
            cell: ({ row: { original } }) => {
                if (original.isBaseline) {
                    return null
                }
                const tone = resultTone(original.variant, metric)
                const positive = isDeltaPositive(original.variant)
                return (
                    <span
                        className={cn(
                            'flex min-w-20 items-center gap-1 whitespace-nowrap text-xs font-semibold',
                            tone === 'success' && 'text-success-foreground',
                            tone === 'destructive' && 'text-destructive-foreground'
                        )}
                    >
                        {formatDeltaPercent(original.variant)}
                        {tone && positive !== undefined && (positive ? <IconTrending /> : <IconTrendingDown />)}
                    </span>
                )
            },
        },
        {
            id: 'win',
            header: () => winChanceHeader(statsMethod, sequentialTestingEnabled),
            enableSorting: false,
            meta: { align: 'center' },
            cell: ({ row: { original } }) => {
                if (original.isBaseline) {
                    return null
                }
                const tone = resultTone(original.variant, metric)
                return (
                    <span
                        className={cn(
                            'inline-block min-w-16 whitespace-nowrap text-xs',
                            tone && 'font-semibold',
                            tone === 'success' && 'text-success-foreground',
                            tone === 'destructive' && 'text-destructive-foreground'
                        )}
                    >
                        {isBayesianResult(original.variant)
                            ? formatChanceToWinForGoal(original.variant, metric.goal)
                            : formatPValue(original.variant.p_value)}
                    </span>
                )
            },
        },
        {
            id: 'chart',
            header: () => <QuillAxisTicks axisRange={axisRange} />,
            enableSorting: false,
            meta: { expand: true },
            minSize: 280,
            cell: ({ row: { original } }) =>
                original.isBaseline ? (
                    axisRange > 0 ? (
                        <BaselineGrid axisRange={axisRange} />
                    ) : (
                        <span className="text-muted-foreground">—</span>
                    )
                ) : (
                    <Tooltip>
                        <TooltipTrigger render={<div className="relative h-10 w-full" data-table-cell="chart" />}>
                            <VariantChart
                                variantResult={original.variant}
                                metric={metric}
                                axisRange={axisRange}
                                metricUuid={metric.uuid}
                                isSecondary={isSecondary}
                                gradientSuffix={gradientSuffix}
                                onTimeseriesClick={timeseries ? () => timeseries(original.variant) : undefined}
                                quill
                            />
                        </TooltipTrigger>
                        <TooltipContent className="max-w-96">
                            <QuillVariantSummary variant={original.variant} metric={metric} isBaseline={false} />
                        </TooltipContent>
                    </Tooltip>
                ),
        },
    ]

    return (
        <DataTable
            columns={columns}
            data={rows}
            fullWidth
            size="sm"
            getRowId={(row) => row.variant.key}
            rowClassName={(row) => {
                const tone = row.isBaseline ? null : resultTone(row.variant, metric)
                return tone === 'success' ? 'bg-success' : tone === 'destructive' ? 'bg-destructive' : undefined
            }}
        />
    )
}
