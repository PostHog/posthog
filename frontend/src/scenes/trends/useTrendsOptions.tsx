import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useDebouncedCallback } from 'use-debounce'

import { IconInfo } from '@posthog/icons'
import { LemonCheckbox, LemonInput, LemonSwitch, Tooltip } from '@posthog/lemon-ui'

import { CompareFilter } from 'lib/components/CompareFilter/CompareFilter'
import { SmoothingFilter } from 'lib/components/SmoothingFilter/SmoothingFilter'
import { smoothingOptions } from 'lib/components/SmoothingFilter/smoothings'
import { UnitPicker } from 'lib/components/UnitPicker/UnitPicker'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonMenuItems } from 'lib/lemon-ui/LemonMenu'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { DEFAULT_DECIMAL_PLACES } from 'lib/utils'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import { axisLabel } from 'scenes/insights/aggregationAxisFormat'
import { HideWeekendsFilter } from 'scenes/insights/EditorFilters/HideWeekendsFilter'
import { LifecycleStackingFilter } from 'scenes/insights/EditorFilters/LifecycleStackingFilter'
import { PercentStackViewFilter } from 'scenes/insights/EditorFilters/PercentStackViewFilter'
import { ScalePicker } from 'scenes/insights/EditorFilters/ScalePicker'
import { ShowAlertAnomalyPointsFilter } from 'scenes/insights/EditorFilters/ShowAlertAnomalyPointsFilter'
import { ShowAlertThresholdLinesFilter } from 'scenes/insights/EditorFilters/ShowAlertThresholdLinesFilter'
import { ShowLegendFilter } from 'scenes/insights/EditorFilters/ShowLegendFilter'
import { ShowMultipleYAxesFilter } from 'scenes/insights/EditorFilters/ShowMultipleYAxesFilter'
import { ShowPieTotalFilter } from 'scenes/insights/EditorFilters/ShowPieTotalFilter'
import { ShowTrendLinesFilter } from 'scenes/insights/EditorFilters/ShowTrendLinesFilter'
import { ValueOnSeriesFilter } from 'scenes/insights/EditorFilters/ValueOnSeriesFilter'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { ConfidenceLevelInput } from 'scenes/insights/views/LineGraph/ConfidenceLevelInput'
import { MovingAverageIntervalsInput } from 'scenes/insights/views/LineGraph/MovingAverageIntervalsInput'

import { hasBreakdownFilter, isWebAnalyticsInsightQuery, isTrendsQuery } from '~/queries/utils'
import { ChartDisplayType } from '~/types'

import { trendsDataLogic } from './trendsDataLogic'

export interface InsightMenuOptions {
    displayItems: LemonMenuItems
    dataItems: LemonMenuItems
    displayActiveCount: number
    dataActiveCount: number
}

function ifShow<T>(condition: boolean | undefined, ...items: T[]): T[] {
    return condition ? items : []
}

/**
 * Builds Display and Data menu items for the trends/stickiness/lifecycle/trendsFunnel
 * insight family. Returns empty arrays for all other insight types.
 */
export function useTrendsOptions(): InsightMenuOptions {
    const { insightProps, canEditInsight, editingDisabledReason } = useValues(insightLogic)
    const {
        querySource,
        isTrends,
        isStickiness,
        isLifecycle,
        display,
        breakdownFilter,
        trendsFilter,
        hasLegend,
        showLegend,
        supportsValueOnSeries,
        showPercentStackView,
        supportsPercentStackView,
        yAxisScaleType,
        showMultipleYAxes,
        isNonTimeSeriesDisplay,
        compareFilter,
        supportsCompare,
        interval,
    } = useValues(insightVizDataLogic(insightProps))
    const { updateQuerySource, updateCompareFilter } = useActions(insightVizDataLogic(insightProps))
    const { isTrendsFunnel } = useValues(funnelDataLogic(insightProps))
    const { featureFlags } = useValues(featureFlagLogic)
    const hideWeekendsEnabled = !!featureFlags[FEATURE_FLAGS.PRODUCT_ANALYTICS_HIDE_WEEKENDS]
    const { showValuesOnSeries, mightContainFractionalNumbers, showConfidenceIntervals, showMovingAverage } = useValues(
        trendsDataLogic(insightProps)
    )

    const isTrendsFamily = isTrends || isStickiness || isLifecycle || isTrendsFunnel
    if (!isTrendsFamily) {
        return { displayItems: [], dataItems: [], displayActiveCount: 0, dataActiveCount: 0 }
    }

    // --- Visibility flags ---
    const isBoxPlot = display === ChartDisplayType.BoxPlot
    const isLineGraph =
        display === ChartDisplayType.ActionsLineGraph ||
        display === ChartDisplayType.ActionsAreaGraph ||
        (!display && isTrendsQuery(querySource))
    const isLinearScale = !yAxisScaleType || yAxisScaleType === 'linear'
    const showCompare =
        (isTrends &&
            display !== ChartDisplayType.ActionsAreaGraph &&
            display !== ChartDisplayType.CalendarHeatmap &&
            display !== ChartDisplayType.BoxPlot) ||
        isStickiness ||
        isWebAnalyticsInsightQuery(querySource)
    const showSmoothing =
        isTrends &&
        !hasBreakdownFilter(breakdownFilter) &&
        (!display || display === ChartDisplayType.ActionsLineGraph || display === ChartDisplayType.ActionsAreaGraph) &&
        (smoothingOptions[interval ?? 'day']?.length ?? 0) > 0
    const showAlertThresholdLinesConfig = isTrends && !isNonTimeSeriesDisplay
    const showMultipleYAxesConfig = (isTrends || isStickiness) && !isNonTimeSeriesDisplay
    const showTimeSeriesDataOptions =
        !isNonTimeSeriesDisplay && isTrends && display !== ChartDisplayType.CalendarHeatmap

    // --- Display items ---
    const boxPlotDisplayItems: LemonMenuItems = [
        ...ifShow(hasLegend, { label: () => <ShowLegendFilter /> }),
        {
            label: () => (
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
                            updateQuerySource({
                                ...querySource,
                                trendsFilter: { ...trendsFilter, excludeBoxPlotOutliers: checked },
                            })
                        }
                    }}
                />
            ),
        },
    ]

    const regularDisplayItems: LemonMenuItems = [
        ...ifShow(isLifecycle, { label: () => <LifecycleStackingFilter /> }),
        ...ifShow(supportsValueOnSeries, { label: () => <ValueOnSeriesFilter /> }),
        ...ifShow(supportsPercentStackView, { label: () => <PercentStackViewFilter /> }),
        ...ifShow(hasLegend, { label: () => <ShowLegendFilter /> }),
        ...ifShow(display === ChartDisplayType.ActionsPie, { label: () => <ShowPieTotalFilter /> }),
        ...ifShow(showAlertThresholdLinesConfig, { label: () => <ShowAlertThresholdLinesFilter /> }),
        ...ifShow(showAlertThresholdLinesConfig, { label: () => <ShowAlertAnomalyPointsFilter /> }),
        ...ifShow(showMultipleYAxesConfig, { label: () => <ShowMultipleYAxesFilter /> }),
        ...ifShow((isTrends || isTrendsFunnel) && !isNonTimeSeriesDisplay, { label: () => <ShowTrendLinesFilter /> }),
        ...ifShow(isTrends && !isNonTimeSeriesDisplay && hideWeekendsEnabled, { label: () => <HideWeekendsFilter /> }),
    ]

    const displayItems: LemonMenuItems = [
        {
            title: (
                <h5 className="mx-2 my-1" data-attr="options-display-section">
                    Display
                </h5>
            ),
            items: isBoxPlot ? boxPlotDisplayItems : regularDisplayItems,
        },
    ]

    // --- Statistical analysis items ---
    const statisticalAnalysisItems: LemonMenuItems = [
        {
            label: () => (
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
                            updateQuerySource({
                                ...querySource,
                                trendsFilter: { ...trendsFilter, showConfidenceIntervals: checked },
                            })
                        }
                    }}
                />
            ),
        },
        ...ifShow(showConfidenceIntervals, { label: () => <ConfidenceLevelInput /> }),
        {
            label: () => (
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
                            updateQuerySource({
                                ...querySource,
                                trendsFilter: { ...trendsFilter, showMovingAverage: checked },
                            })
                        }
                    }}
                />
            ),
        },
        ...ifShow(showMovingAverage, { label: () => <MovingAverageIntervalsInput /> }),
    ]

    // --- Data items ---
    const dataItems: LemonMenuItems = [
        ...ifShow(showCompare, {
            title: 'Compare',
            items: [
                {
                    label: () => (
                        <div className="mx-2 mb-2.5">
                            <CompareFilter
                                compareFilter={compareFilter}
                                updateCompareFilter={updateCompareFilter}
                                disabled={!canEditInsight || !supportsCompare}
                                disableReason={editingDisabledReason}
                                fullWidth
                            />
                        </div>
                    ),
                },
            ],
        }),
        ...ifShow(showSmoothing, {
            title: 'Smoothing',
            items: [
                {
                    label: () => (
                        <div className="mx-2 mb-2.5">
                            <SmoothingFilter fullWidth />
                        </div>
                    ),
                },
            ],
        }),
        ...ifShow(!showPercentStackView && isTrends && display !== ChartDisplayType.CalendarHeatmap, {
            title: axisLabel(display || ChartDisplayType.ActionsLineGraph),
            items: [{ label: () => <UnitPicker /> }],
        }),
        ...ifShow(showTimeSeriesDataOptions, {
            title: 'Y-axis scale',
            items: [{ label: () => <ScalePicker /> }],
        }),
        ...ifShow(showTimeSeriesDataOptions && !isBoxPlot, {
            title: 'Statistical analysis',
            items: statisticalAnalysisItems,
        }),
        ...ifShow(mightContainFractionalNumbers && isTrends && display !== ChartDisplayType.CalendarHeatmap, {
            title: 'Decimal places',
            items: [{ label: () => <DecimalPrecisionInput /> }],
        }),
    ]

    // --- Active-option badge counts ---
    const displayActiveCount =
        (supportsValueOnSeries && showValuesOnSeries ? 1 : 0) +
        (showPercentStackView ? 1 : 0) +
        (hasLegend && showLegend ? 1 : 0) +
        (showMultipleYAxes ? 1 : 0) +
        (trendsFilter?.hideWeekends && hideWeekendsEnabled ? 1 : 0)
    const dataActiveCount =
        (!showPercentStackView &&
        isTrends &&
        trendsFilter?.aggregationAxisFormat &&
        trendsFilter.aggregationAxisFormat !== 'numeric'
            ? 1
            : 0) +
        (!!yAxisScaleType && yAxisScaleType !== 'linear' ? 1 : 0) +
        (showCompare && !!compareFilter?.compare ? 1 : 0) +
        (showSmoothing && !!trendsFilter?.smoothingIntervals && trendsFilter.smoothingIntervals > 1 ? 1 : 0)

    return { displayItems, dataItems, displayActiveCount, dataActiveCount }
}

function DecimalPrecisionInput(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { trendsFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    const reportChange = useDebouncedCallback(() => {
        posthog.capture('decimal places changed', { decimal_places: trendsFilter?.decimalPlaces })
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
