import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { ReactNode, useEffect, useState } from 'react'
import { useDebouncedCallback } from 'use-debounce'

import { IconChevronDown, IconChevronRight, IconInfo } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonInput, LemonSwitch, Tooltip } from '@posthog/lemon-ui'

import { SmoothingFilter } from 'lib/components/SmoothingFilter/SmoothingFilter'
import { UnitPicker } from 'lib/components/UnitPicker/UnitPicker'
import { LemonMenuItem } from 'lib/lemon-ui/LemonMenu'
import { DEFAULT_DECIMAL_PLACES } from 'lib/utils/numbers'
import { AxisLabelsFilter } from 'scenes/insights/EditorFilters/AxisLabelsFilter'
import { HideIncompleteConversionWindowPeriodsFilter } from 'scenes/insights/EditorFilters/HideIncompleteConversionWindowPeriodsFilter'
import { HideWeekendsFilter } from 'scenes/insights/EditorFilters/HideWeekendsFilter'
import { LegendOptionsFilter } from 'scenes/insights/EditorFilters/LegendOptionsFilter'
import { LifecyclePercentagesFilter } from 'scenes/insights/EditorFilters/LifecyclePercentagesFilter'
import { LifecycleStackingFilter } from 'scenes/insights/EditorFilters/LifecycleStackingFilter'
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
import { StackBreakdownFilter } from 'scenes/insights/EditorFilters/StackBreakdownFilter'
import { ValueOnSeriesFilter } from 'scenes/insights/EditorFilters/ValueOnSeriesFilter'
import { RetentionCohortLabelStartIndexPicker } from 'scenes/insights/filters/RetentionCohortLabelStartIndexPicker'
import { RetentionDashboardDisplayPicker } from 'scenes/insights/filters/RetentionDashboardDisplayPicker'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { ConfidenceLevelInput } from 'scenes/insights/views/LineGraph/ConfidenceLevelInput'
import { MovingAverageIntervalsInput } from 'scenes/insights/views/LineGraph/MovingAverageIntervalsInput'
import { trendsDataLogic } from 'scenes/trends/trendsDataLogic'

import { isTrendsQuery } from '~/queries/utils'
import { ChartDisplayType } from '~/types'

export const LINE_DISPLAYS = [
    ChartDisplayType.ActionsLineGraph,
    ChartDisplayType.ActionsLineGraphCumulative,
    ChartDisplayType.ActionsAreaGraph,
] as const
export const BAR_DISPLAYS = [
    ChartDisplayType.ActionsBar,
    ChartDisplayType.ActionsUnstackedBar,
    ChartDisplayType.ActionsBarValue,
] as const

export function displayMatches(
    display: ChartDisplayType | null | undefined,
    displays: readonly ChartDisplayType[]
): boolean {
    return !!display && displays.includes(display)
}

export function isDefaultTrendsLineDisplay(
    display: ChartDisplayType | null | undefined,
    querySource: Parameters<typeof isTrendsQuery>[0]
): boolean {
    return !display && isTrendsQuery(querySource)
}

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

function PercentStack(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { display } = useValues(insightVizDataLogic(insightProps))
    const { showValuesOnSeries } = useValues(trendsDataLogic(insightProps))

    return (
        <PercentStackViewFilter
            // On a pie chart the percentage is rendered through the series value labels, so it has no
            // effect while those labels are hidden.
            disabledReason={
                display === ChartDisplayType.ActionsPie && showValuesOnSeries === false
                    ? "Enable 'Show values on series' to use this option"
                    : undefined
            }
        />
    )
}

export function ConfidenceInterval(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { querySource, trendsFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateQuerySource } = useActions(insightVizDataLogic(insightProps))
    const { showConfidenceIntervals } = useValues(trendsDataLogic(insightProps))
    const { isLineGraph, isLinearScale } = useLineGraphState()

    return (
        <LemonSwitch
            label="Show confidence intervals"
            className="pb-2"
            fullWidth
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

export function MovingAverage(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { querySource, trendsFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateQuerySource } = useActions(insightVizDataLogic(insightProps))
    const { showMovingAverage } = useValues(trendsDataLogic(insightProps))
    const { isLineGraph, isLinearScale } = useLineGraphState()

    return (
        <LemonSwitch
            label="Show moving average"
            className="pb-2"
            fullWidth
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

export function DecimalPrecision(): JSX.Element {
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

/** A menu row that expands its options inline, accordion-style. Nested popovers are awkward to
 * use inside a menu, so collapsed option groups expand within the same overlay instead. */
const COLLAPSIBLE_TRANSITION_MS = 200

export function CollapsibleOptionsSection({
    label,
    dataAttr,
    defaultExpanded = false,
    children,
}: {
    label: string
    dataAttr?: string
    defaultExpanded?: boolean
    children: ReactNode
}): JSX.Element {
    const [expanded, setExpanded] = useState(defaultExpanded)
    // The content is only in the DOM while the section is (at least partially) open: it mounts as
    // the expand transition starts and unmounts once the collapse transition ends. Keeping it
    // permanently mounted-but-hidden made the popover prone to stale paints (controls not
    // rendering until hovered).
    const [showContent, setShowContent] = useState(defaultExpanded)

    useEffect(() => {
        if (expanded) {
            setShowContent(true)
        } else {
            const timeout = setTimeout(() => setShowContent(false), COLLAPSIBLE_TRANSITION_MS)
            return () => clearTimeout(timeout)
        }
    }, [expanded])

    return (
        // The min-width keeps the menu width stable when a section expands
        <div className="flex flex-col w-full min-w-[18rem]" data-attr={dataAttr}>
            <LemonButton
                fullWidth
                size="small"
                onClick={() => setExpanded(!expanded)}
                sideIcon={expanded ? <IconChevronDown /> : <IconChevronRight />}
                aria-expanded={expanded}
            >
                {label}
            </LemonButton>
            <div
                className="grid transition-all duration-200 ease-in-out"
                style={{ gridTemplateRows: expanded && showContent ? '1fr' : '0fr' }}
            >
                <div className="overflow-hidden">
                    {showContent && <div className="flex flex-col pt-2 pb-1 pl-2 w-full">{children}</div>}
                </div>
            </div>
        </div>
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

// Every insight display toggle as a ready-to-use menu item, so callers assemble the Options menu by
// referencing `DisplayOptions.X` instead of repeating `{ label: () => <X /> }` for each one.
export const DisplayOptions = {
    Smoothing: { label: () => <Smoothing /> },
    Legend: { label: () => <ShowLegendFilter /> },
    LegendOptions: { label: () => <LegendOptionsFilter /> },
    ExcludeOutliers: { label: () => <ExcludeOutliers /> },
    MetricSummary: { label: () => <MetricSummaryFilter /> },
    MetricShowChange: { label: () => <MetricShowChangeFilter /> },
    MetricColor: { label: () => <MetricColorFilter /> },
    LifecycleStacking: { label: () => <LifecycleStackingFilter /> },
    LifecyclePercentages: { label: () => <LifecyclePercentagesFilter /> },
    ValueLabels: { label: () => <ValueOnSeriesFilter /> },
    PercentStack: { label: () => <PercentStack /> },
    StackBreakdown: { label: () => <StackBreakdownFilter /> },
    PieTotal: { label: () => <ShowPieTotalFilter /> },
    AlertThresholdLines: { label: () => <ShowAlertThresholdLinesFilter /> },
    AlertAnomalyPoints: { label: () => <ShowAlertAnomalyPointsFilter /> },
    MultipleYAxes: { label: () => <ShowMultipleYAxesFilter /> },
    TrendLines: { label: () => <ShowTrendLinesFilter /> },
    HideIncompleteFunnelPeriods: { label: () => <HideIncompleteConversionWindowPeriodsFilter /> },
    HideWeekends: { label: () => <HideWeekendsFilter /> },
    Annotations: { label: () => <ShowAnnotationsFilter /> },
    ResultCustomizationBy: { label: () => <ResultCustomizationByPicker /> },
    Unit: { label: () => <UnitPicker /> },
    Scale: { label: () => <ScalePicker /> },
    ConfidenceInterval: { label: () => <ConfidenceInterval /> },
    ConfidenceLevel: { label: () => <ConfidenceLevelInput /> },
    MovingAverage: { label: () => <MovingAverage /> },
    MovingAverageIntervals: { label: () => <MovingAverageIntervalsInput /> },
    AxisLabels: { label: () => <AxisLabelsFilter /> },
    DecimalPrecision: { label: () => <DecimalPrecision /> },
    RetentionDashboardDisplay: { label: () => <RetentionDashboardDisplayPicker /> },
    RetentionCohortLabelStart: { label: () => <RetentionCohortLabelStartIndexPicker /> },
} satisfies Record<string, LemonMenuItem>
