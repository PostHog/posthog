import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { ReactNode } from 'react'
import { useDebouncedCallback } from 'use-debounce'

import { IconInfo } from '@posthog/icons'
import { LemonCheckbox, LemonInput, Tooltip } from '@posthog/lemon-ui'

import { SmoothingFilter } from 'lib/components/SmoothingFilter/SmoothingFilter'
import { UnitPicker } from 'lib/components/UnitPicker/UnitPicker'
import { DEFAULT_DECIMAL_PLACES } from 'lib/utils/numbers'
import { AxisLabelFilter } from 'scenes/insights/EditorFilters/AxisLabelFilter'
import { HideIncompleteConversionWindowPeriodsFilter } from 'scenes/insights/EditorFilters/HideIncompleteConversionWindowPeriodsFilter'
import { LegendOptionsFilter } from 'scenes/insights/EditorFilters/LegendOptionsFilter'
import { LifecyclePercentagesFilter } from 'scenes/insights/EditorFilters/LifecyclePercentagesFilter'
import { LifecycleStackingFilter } from 'scenes/insights/EditorFilters/LifecycleStackingFilter'
import { LineStylePicker } from 'scenes/insights/EditorFilters/LineStylePicker'
import {
    MetricColorFilter,
    MetricShowChangeFilter,
    MetricSummaryFilter,
} from 'scenes/insights/EditorFilters/MetricFilters'
import { PercentStackViewFilter } from 'scenes/insights/EditorFilters/PercentStackViewFilter'
import { ResultCustomizationByPicker } from 'scenes/insights/EditorFilters/ResultCustomizationByPicker'
import { ScalePicker } from 'scenes/insights/EditorFilters/ScalePicker'
import { ShowAlertAnomalyPointsFilter } from 'scenes/insights/EditorFilters/ShowAlertAnomalyPointsFilter'
import { ShowAlertThresholdLinesFilter } from 'scenes/insights/EditorFilters/ShowAlertThresholdLinesFilter'
import { ShowAnnotationsFilter } from 'scenes/insights/EditorFilters/ShowAnnotationsFilter'
import { ShowLegendFilter } from 'scenes/insights/EditorFilters/ShowLegendFilter'
import { ShowMultipleYAxesFilter } from 'scenes/insights/EditorFilters/ShowMultipleYAxesFilter'
import { ShowPieTotalFilter } from 'scenes/insights/EditorFilters/ShowPieTotalFilter'
import { ShowTrendLinesFilter } from 'scenes/insights/EditorFilters/ShowTrendLinesFilter'
import { SliceNamesFilter } from 'scenes/insights/EditorFilters/SliceNamesFilter'
import { StackBreakdownFilter } from 'scenes/insights/EditorFilters/StackBreakdownFilter'
import { ValueOnSeriesFilter } from 'scenes/insights/EditorFilters/ValueOnSeriesFilter'
import { YAxisRangeFilter } from 'scenes/insights/EditorFilters/YAxisRangeFilter'
import { RetentionCohortLabelStartIndexPicker } from 'scenes/insights/filters/RetentionCohortLabelStartIndexPicker'
import { RetentionDashboardDisplayPicker } from 'scenes/insights/filters/RetentionDashboardDisplayPicker'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { ConfidenceLevelInput } from 'scenes/insights/views/LineGraph/ConfidenceLevelInput'
import { MovingAverageIntervalsInput } from 'scenes/insights/views/LineGraph/MovingAverageIntervalsInput'
import { trendsDataLogic } from 'scenes/trends/trendsDataLogic'

import { isTrendsQuery } from '~/queries/utils'
import { ChartDisplayType } from '~/types'

import { displayMatches, isDefaultTrendsLineDisplay, LINE_DISPLAYS } from './displayTypes'

function useLineGraphState(): { isLineGraph: boolean; isLinearScale: boolean } {
    const { insightProps } = useValues(insightLogic)
    const { querySource, display, yAxisScaleType } = useValues(insightVizDataLogic(insightProps))
    const isLineDisplay = isDefaultTrendsLineDisplay(display, querySource) || displayMatches(display, LINE_DISPLAYS)
    const isCumulativeLineDisplay = display === ChartDisplayType.ActionsLineGraphCumulative
    return {
        isLineGraph: isLineDisplay && !isCumulativeLineDisplay,
        isLinearScale: !yAxisScaleType || yAxisScaleType === 'linear',
    }
}

function Smoothing(): JSX.Element {
    return (
        <div className="px-2 pb-1.5 w-full">
            <SmoothingFilter />
        </div>
    )
}

function ExcludeOutliers(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { querySource, trendsFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateQuerySource } = useActions(insightVizDataLogic(insightProps))

    return (
        <LemonCheckbox
            label={
                <span className="font-normal">
                    Exclude outliers{' '}
                    <Tooltip title="When enabled, whiskers are clipped to 1.5x the interquartile range, making it easier to see differences between the quartiles. When disabled, the y-axis extends to show the full range including extreme values.">
                        <IconInfo className="relative top-0.5 text-lg text-secondary" />
                    </Tooltip>
                </span>
            }
            className="p-1 px-2"
            size="small"
            checked={trendsFilter?.excludeBoxPlotOutliers !== false}
            onChange={(checked) => {
                if (isTrendsQuery(querySource)) {
                    const newQuery = { ...querySource }
                    newQuery.trendsFilter = { ...trendsFilter, excludeBoxPlotOutliers: checked }
                    updateQuerySource(newQuery)
                }
            }}
        />
    )
}

function ConfidenceInterval(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { querySource, trendsFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateQuerySource } = useActions(insightVizDataLogic(insightProps))
    const { showConfidenceIntervals } = useValues(trendsDataLogic(insightProps))
    const { isLineGraph, isLinearScale } = useLineGraphState()

    return (
        <LemonCheckbox
            label={<span className="font-normal">Show confidence intervals</span>}
            className="p-1 px-2"
            size="small"
            checked={showConfidenceIntervals}
            disabledReason={
                !isLineGraph
                    ? 'Confidence intervals are only available for line graphs'
                    : !isLinearScale
                      ? 'Confidence intervals are only supported for linear scale.'
                      : undefined
            }
            onChange={(checked) => {
                if (isTrendsQuery(querySource)) {
                    const newQuery = { ...querySource }
                    newQuery.trendsFilter = { ...trendsFilter, showConfidenceIntervals: checked }
                    updateQuerySource(newQuery)
                }
            }}
        />
    )
}

function MovingAverage(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { querySource, trendsFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateQuerySource } = useActions(insightVizDataLogic(insightProps))
    const { showMovingAverage } = useValues(trendsDataLogic(insightProps))
    const { isLineGraph, isLinearScale } = useLineGraphState()

    return (
        <LemonCheckbox
            label={<span className="font-normal">Show moving average</span>}
            className="p-1 px-2"
            size="small"
            checked={showMovingAverage}
            disabledReason={
                !isLineGraph
                    ? 'Moving average is only available for line and area graphs'
                    : !isLinearScale
                      ? 'Moving average is only supported for linear scale.'
                      : undefined
            }
            onChange={(checked) => {
                if (isTrendsQuery(querySource)) {
                    const newQuery = { ...querySource }
                    newQuery.trendsFilter = { ...trendsFilter, showMovingAverage: checked }
                    updateQuerySource(newQuery)
                }
            }}
        />
    )
}

function DecimalPrecision(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { trendsFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    const reportChange = useDebouncedCallback(() => {
        posthog.capture('decimal places changed', {
            decimal_places: trendsFilter?.decimalPlaces,
        })
    }, 500)

    return (
        <LemonInput
            type="number"
            size="small"
            step={1}
            min={0}
            max={9}
            defaultValue={DEFAULT_DECIMAL_PLACES}
            value={trendsFilter?.decimalPlaces}
            onChange={(value) => {
                updateInsightFilter({ decimalPlaces: value })
                reportChange()
            }}
            className="mx-2 mb-1.5"
        />
    )
}

export function SectionHeader({
    children,
    tooltip,
    dataAttr,
}: {
    children: ReactNode
    tooltip?: string
    dataAttr?: string
}): JSX.Element {
    return (
        <h5 className="mx-2 my-1" data-attr={dataAttr}>
            {children}
            {tooltip && (
                <>
                    {' '}
                    <Tooltip title={tooltip}>
                        <IconInfo className="relative top-0.5 text-lg text-secondary" />
                    </Tooltip>
                </>
            )}
        </h5>
    )
}

// Every insight display toggle, keyed so the Options panel is assembled by referencing
// `DisplayOptions.X` instead of importing each filter component.
export const DisplayOptions = {
    Smoothing,
    Legend: ShowLegendFilter,
    LegendOptions: LegendOptionsFilter,
    ExcludeOutliers,
    MetricSummary: MetricSummaryFilter,
    MetricShowChange: MetricShowChangeFilter,
    MetricColor: MetricColorFilter,
    LifecycleStacking: LifecycleStackingFilter,
    LifecyclePercentages: LifecyclePercentagesFilter,
    ValueLabels: ValueOnSeriesFilter,
    PercentStack: PercentStackViewFilter,
    StackBreakdown: StackBreakdownFilter,
    SliceNames: SliceNamesFilter,
    PieTotal: ShowPieTotalFilter,
    AlertThresholdLines: ShowAlertThresholdLinesFilter,
    AlertAnomalyPoints: ShowAlertAnomalyPointsFilter,
    MultipleYAxes: ShowMultipleYAxesFilter,
    TrendLines: ShowTrendLinesFilter,
    HideIncompleteFunnelPeriods: HideIncompleteConversionWindowPeriodsFilter,
    Annotations: ShowAnnotationsFilter,
    ResultCustomizationBy: ResultCustomizationByPicker,
    Unit: UnitPicker,
    Scale: ScalePicker,
    YAxisRange: YAxisRangeFilter,
    LineStyle: LineStylePicker,
    ConfidenceInterval,
    ConfidenceLevel: ConfidenceLevelInput,
    MovingAverage,
    MovingAverageIntervals: MovingAverageIntervalsInput,
    XAxisLabel: () => <AxisLabelFilter axis="x" />,
    YAxisLabel: () => <AxisLabelFilter axis="y" />,
    DecimalPrecision,
    RetentionDashboardDisplay: RetentionDashboardDisplayPicker,
    RetentionCohortLabelStart: RetentionCohortLabelStartIndexPicker,
} satisfies Record<string, () => JSX.Element | null>

export type DisplayOption = (typeof DisplayOptions)[keyof typeof DisplayOptions]
