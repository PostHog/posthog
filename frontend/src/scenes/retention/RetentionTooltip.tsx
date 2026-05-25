import { useCallback, useMemo } from 'react'

import type { TooltipContext } from 'lib/hog-charts'
import { roundToDecimal } from 'lib/utils'
import { InsightTooltip } from 'scenes/insights/InsightTooltip/InsightTooltip'
import type { SeriesDatum } from 'scenes/insights/InsightTooltip/insightTooltipUtils'

import type { RetentionSeriesMeta } from './retentionChartTransforms'

const NOOP = (): void => {}

interface RetentionTooltipProps {
    context: TooltipContext<RetentionSeriesMeta>
    xAxisLabels: string[]
    period?: string
    selectedInterval: number | null
    shouldShowMeanPerBreakdown: boolean
    isPercentage: boolean
    groupTypeLabel?: string
    onRowClick?: (datum: SeriesDatum) => void
}

export function RetentionTooltip({
    context,
    xAxisLabels,
    period,
    selectedInterval,
    shouldShowMeanPerBreakdown,
    isPercentage,
    groupTypeLabel,
    onRowClick,
}: RetentionTooltipProps): React.ReactElement {
    const seriesData = useMemo<SeriesDatum[]>(
        () =>
            context.seriesData
                .map((entry, idx) => ({
                    id: idx,
                    dataIndex: context.dataIndex,
                    datasetIndex: idx,
                    order: entry.series.meta?.rowIndex ?? idx,
                    label: entry.series.label,
                    color: entry.color,
                    count: entry.value,
                    breakdown_value:
                        entry.series.meta?.breakdown_value != null
                            ? String(entry.series.meta.breakdown_value)
                            : undefined,
                }))
                // Show highest values first, matching the legacy LineGraph tooltip.
                .sort((a, b) => b.count - a.count || (a.label ?? '').localeCompare(b.label ?? ''))
                .map((datum, id) => ({ ...datum, id })),
        [context.seriesData, context.dataIndex]
    )

    const renderCount = useCallback(
        (value: number): string => (isPercentage ? `${roundToDecimal(value)}%` : `${roundToDecimal(value)}`),
        [isPercentage]
    )

    const renderSeries = useCallback(
        (value: React.ReactNode): React.ReactElement => {
            const showCohortPrefix = selectedInterval !== null || !shouldShowMeanPerBreakdown
            return <>{showCohortPrefix ? <>Cohort {value}</> : value}</>
        },
        [selectedInterval, shouldShowMeanPerBreakdown]
    )

    const title =
        selectedInterval !== null ? `${period} ${selectedInterval}` : (xAxisLabels[context.dataIndex] ?? context.label)

    return (
        <InsightTooltip
            altTitle={title}
            seriesData={seriesData}
            groupTypeLabel={groupTypeLabel}
            onClose={context.onUnpin ?? NOOP}
            renderSeries={renderSeries}
            renderCount={renderCount}
            onRowClick={onRowClick}
            hideInspectActorsSection={!onRowClick}
        />
    )
}
