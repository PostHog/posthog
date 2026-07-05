import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { type ChangeEvent, type KeyboardEvent, ReactNode, useEffect, useMemo, useState } from 'react'
import { useDebouncedCallback } from 'use-debounce'

import { IconInfo } from '@posthog/icons'
import {
    Button,
    Input,
    Label,
    Popover,
    PopoverContent,
    PopoverTrigger,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Separator,
    Switch,
    ToggleGroup,
    ToggleGroupItem,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'
import { normalizeAxisLabel } from '@posthog/quill-charts'

import { insightAlertsLogic } from 'lib/components/Alerts/insightAlertsLogic'
import { smoothingOptions } from 'lib/components/SmoothingFilter/smoothings'
import { unitPickerModalLogic } from 'lib/components/UnitPicker/unitPickerModalLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { DEFAULT_DECIMAL_PLACES } from 'lib/utils/numbers'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import {
    AggregationAxisFormat,
    defaultAggregationAxisFormatForDisplay,
    INSIGHT_UNIT_OPTIONS,
    INSIGHT_UNIT_OPTIONS_SHORT,
} from 'scenes/insights/aggregationAxisFormat'
import { DirectionColorPickers } from 'scenes/insights/EditorFilters/MetricFilters'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import {
    METRIC_COLOR_BY_DIRECTION_DEFAULT,
    METRIC_DEFAULT_DECREASE_COLOR,
    METRIC_DEFAULT_INCREASE_COLOR,
    METRIC_SHOW_CHANGE_DEFAULT,
    METRIC_SUMMARY_DEFAULT,
    type MetricSummary,
} from 'scenes/insights/views/Metric/Metric.utils'
import { INTERVAL_TO_DEFAULT_MOVING_AVERAGE_PERIOD, trendsDataLogic } from 'scenes/trends/trendsDataLogic'

import { ResultCustomizationBy, type TrendsFilter } from '~/queries/schema/schema-general'
import { isFunnelsQuery, isRetentionQuery, isTrendsQuery } from '~/queries/utils'
import { ChartDisplayType, RetentionDashboardDisplayType } from '~/types'

import { DisplayOptionKey, useLineGraphState } from './DisplayOptions'

export function OptionTooltip({ children }: { children: ReactNode }): JSX.Element {
    return (
        <Tooltip>
            <TooltipTrigger render={<span className="inline-flex text-muted-foreground" />}>
                <IconInfo />
            </TooltipTrigger>
            <TooltipContent side="top" className="max-w-72">
                {children}
            </TooltipContent>
        </Tooltip>
    )
}

function OptionSwitchRow({
    id,
    label,
    checked,
    onCheckedChange,
    disabledReason,
    tooltip,
}: {
    id: string
    label: string
    checked: boolean
    onCheckedChange: (checked: boolean) => void
    disabledReason?: string
    tooltip?: string
}): JSX.Element {
    return (
        <div className="flex items-center gap-2 px-3 py-1.5" title={disabledReason}>
            <Switch id={id} size="sm" checked={checked} onCheckedChange={onCheckedChange} disabled={!!disabledReason} />
            <Label htmlFor={id} className="font-normal">
                {label}
            </Label>
            {tooltip && <OptionTooltip>{tooltip}</OptionTooltip>}
        </div>
    )
}

function SmoothingNext(): JSX.Element | null {
    const { insightProps, editingDisabledReason } = useValues(insightLogic)
    const { isTrends, interval, trendsFilter } = useValues(trendsDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    if (!isTrends || !interval) {
        return null
    }
    const options = smoothingOptions[interval]
    if (!options.length) {
        return null
    }
    const items = Object.fromEntries(options.map((option) => [String(option.value), option.label]))

    return (
        <div className="px-3 py-1">
            <Select
                value={String(trendsFilter?.smoothingIntervals || 1)}
                items={items}
                onValueChange={(value: string | null) => {
                    if (value) {
                        updateInsightFilter({ smoothingIntervals: parseInt(value) })
                    }
                }}
                disabled={!!editingDisabledReason}
            >
                <SelectTrigger
                    size="sm"
                    className="w-full"
                    data-attr="smoothing-filter"
                    title={editingDisabledReason ?? undefined}
                >
                    <SelectValue />
                </SelectTrigger>
                <SelectContent>
                    {options.map((option) => (
                        <SelectItem key={option.value} value={String(option.value)}>
                            {option.label}
                        </SelectItem>
                    ))}
                </SelectContent>
            </Select>
        </div>
    )
}

function LegendNext(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { showLegend } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    return (
        <OptionSwitchRow
            id="insight-option-show-legend"
            label="Show legend"
            checked={!!showLegend}
            onCheckedChange={() => updateInsightFilter({ showLegend: !showLegend })}
        />
    )
}

type LegendPosition = NonNullable<TrendsFilter['legendPosition']>

const LEGEND_POSITION_OPTIONS: { value: LegendPosition; label: string }[] = [
    { value: 'bottom', label: 'Bottom' },
    { value: 'top', label: 'Top' },
    { value: 'left', label: 'Left' },
    { value: 'right', label: 'Right' },
]

function LegendOptionsNext(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { showLegend, legendPosition } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    return (
        <div className="flex items-center justify-between gap-2 px-3 py-1.5">
            <div className="flex items-center gap-2">
                <Switch
                    id="insight-option-legend-options"
                    size="sm"
                    checked={!!showLegend}
                    onCheckedChange={(checked) =>
                        updateInsightFilter({
                            showLegend: checked,
                            // Seed bottom on first enable — old insights without a saved position render right (chart-config fallback).
                            ...(checked && legendPosition == null ? { legendPosition: 'bottom' } : {}),
                        })
                    }
                />
                <Label htmlFor="insight-option-legend-options" className="font-normal">
                    Show legend
                </Label>
            </div>
            <Select
                value={(legendPosition ?? (showLegend ? 'right' : 'bottom')) as string}
                items={Object.fromEntries(LEGEND_POSITION_OPTIONS.map((option) => [option.value, option.label]))}
                onValueChange={(position: string | null) => {
                    if (position) {
                        updateInsightFilter({ legendPosition: position as LegendPosition })
                    }
                }}
                disabled={!showLegend}
            >
                <SelectTrigger size="sm" title={!showLegend ? 'Enable the legend to set its position' : undefined}>
                    <SelectValue />
                </SelectTrigger>
                <SelectContent>
                    {LEGEND_POSITION_OPTIONS.map((option) => (
                        <SelectItem key={option.value} value={option.value}>
                            {option.label}
                        </SelectItem>
                    ))}
                </SelectContent>
            </Select>
        </div>
    )
}

function ExcludeOutliersNext(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { querySource, trendsFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateQuerySource } = useActions(insightVizDataLogic(insightProps))

    return (
        <OptionSwitchRow
            id="insight-option-exclude-outliers"
            label="Exclude outliers"
            tooltip="When enabled, whiskers are clipped to 1.5x the interquartile range, making it easier to see differences between the quartiles. When disabled, the y-axis extends to show the full range including extreme values."
            checked={trendsFilter?.excludeBoxPlotOutliers !== false}
            onCheckedChange={(checked) => {
                if (isTrendsQuery(querySource)) {
                    updateQuerySource({
                        ...querySource,
                        trendsFilter: { ...trendsFilter, excludeBoxPlotOutliers: checked },
                    })
                }
            }}
        />
    )
}

function MetricSummaryNext(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { trendsFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    const summary = trendsFilter?.metricSummary ?? METRIC_SUMMARY_DEFAULT

    return (
        <div className="flex items-center justify-between gap-2 px-3 py-1.5">
            <span className="font-normal">Headline value</span>
            <Select
                value={summary}
                items={{ total: 'Total', average: 'Average', latest: 'Latest' }}
                onValueChange={(value: string | null) => {
                    if (value) {
                        updateInsightFilter({ metricSummary: value as MetricSummary })
                    }
                }}
            >
                <SelectTrigger size="sm">
                    <SelectValue />
                </SelectTrigger>
                <SelectContent>
                    <SelectItem value="total">Total</SelectItem>
                    <SelectItem value="average">Average</SelectItem>
                    <SelectItem value="latest">Latest</SelectItem>
                </SelectContent>
            </Select>
        </div>
    )
}

function MetricShowChangeNext(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { trendsFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    const showChange = trendsFilter?.metricShowChange ?? METRIC_SHOW_CHANGE_DEFAULT

    return (
        <div className="flex flex-col">
            <OptionSwitchRow
                id="insight-option-metric-show-change"
                label="Show change"
                checked={showChange}
                onCheckedChange={() => updateInsightFilter({ metricShowChange: !showChange })}
            />
            {showChange && (
                <DirectionColorPickers
                    increaseColor={trendsFilter?.metricChangeIncreaseColor ?? METRIC_DEFAULT_INCREASE_COLOR}
                    decreaseColor={trendsFilter?.metricChangeDecreaseColor ?? METRIC_DEFAULT_DECREASE_COLOR}
                    onIncrease={(color) => updateInsightFilter({ metricChangeIncreaseColor: color })}
                    onDecrease={(color) => updateInsightFilter({ metricChangeDecreaseColor: color })}
                />
            )}
        </div>
    )
}

function MetricColorNext(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { trendsFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    const colorByDirection = trendsFilter?.metricColorByDirection ?? METRIC_COLOR_BY_DIRECTION_DEFAULT

    return (
        <div className="flex flex-col">
            <OptionSwitchRow
                id="insight-option-metric-color"
                label="Color by trend"
                checked={colorByDirection}
                onCheckedChange={() => updateInsightFilter({ metricColorByDirection: !colorByDirection })}
            />
            {colorByDirection && (
                <DirectionColorPickers
                    increaseColor={trendsFilter?.metricLineIncreaseColor ?? METRIC_DEFAULT_INCREASE_COLOR}
                    decreaseColor={trendsFilter?.metricLineDecreaseColor ?? METRIC_DEFAULT_DECREASE_COLOR}
                    onIncrease={(color) => updateInsightFilter({ metricLineIncreaseColor: color })}
                    onDecrease={(color) => updateInsightFilter({ metricLineDecreaseColor: color })}
                />
            )}
        </div>
    )
}

function LifecycleStackingNext(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { lifecycleFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    return (
        <OptionSwitchRow
            id="insight-option-lifecycle-stacking"
            label="Stack bars"
            checked={lifecycleFilter?.stacked ?? true}
            onCheckedChange={(checked) => updateInsightFilter({ stacked: checked })}
        />
    )
}

function LifecyclePercentagesNext(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { showPercentagesOnSeries } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    return (
        <OptionSwitchRow
            id="insight-option-lifecycle-percentages"
            label="Show percentages on series"
            checked={!!showPercentagesOnSeries}
            onCheckedChange={() => updateInsightFilter({ showPercentagesOnSeries: !showPercentagesOnSeries })}
        />
    )
}

function ValueLabelsNext(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { showValuesOnSeries } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    return (
        <OptionSwitchRow
            id="insight-option-value-labels"
            label="Show values on series"
            checked={!!showValuesOnSeries}
            onCheckedChange={() => updateInsightFilter({ showValuesOnSeries: !showValuesOnSeries })}
        />
    )
}

function PercentStackNext(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { display } = useValues(insightVizDataLogic(insightProps))
    const { showPercentStackView, showValuesOnSeries } = useValues(trendsDataLogic(insightProps))
    const { updateInsightFilter } = useActions(trendsDataLogic(insightProps))

    return (
        <OptionSwitchRow
            id="insight-option-percent-stack"
            label="Show as % of total"
            checked={!!showPercentStackView}
            onCheckedChange={(checked) => updateInsightFilter({ showPercentStackView: checked })}
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

function StackBreakdownNext(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { trendsFilter } = useValues(trendsDataLogic(insightProps))
    const { updateInsightFilter } = useActions(trendsDataLogic(insightProps))

    return (
        <OptionSwitchRow
            id="insight-option-stack-breakdown"
            label="Stack breakdown values"
            checked={!!trendsFilter?.stackBreakdownValues}
            onCheckedChange={(checked) => updateInsightFilter({ stackBreakdownValues: checked })}
        />
    )
}

function PieTotalNext(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { pieChartVizOptions } = useValues(trendsDataLogic(insightProps))
    const { updateVizSpecificOptions } = useActions(insightVizDataLogic(insightProps))

    const showTotal = !pieChartVizOptions?.hideAggregation

    return (
        <OptionSwitchRow
            id="insight-option-pie-total"
            label="Show total below chart"
            checked={showTotal}
            onCheckedChange={() =>
                updateVizSpecificOptions({
                    [ChartDisplayType.ActionsPie]: { ...pieChartVizOptions, hideAggregation: showTotal },
                })
            }
        />
    )
}

function AlertThresholdLinesNext(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { showAlertThresholdLines } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    return (
        <OptionSwitchRow
            id="insight-option-alert-threshold-lines"
            label="Show alert threshold lines"
            checked={!!showAlertThresholdLines}
            onCheckedChange={() => updateInsightFilter({ showAlertThresholdLines: !showAlertThresholdLines })}
        />
    )
}

function AlertAnomalyPointsNext(): JSX.Element | null {
    const { insightProps, insight } = useValues(insightLogic)
    const logic = insightAlertsLogic({ insightId: insight.id!, insightLogicProps: insightProps })
    const { showAlertAnomalyPointsFlag, hasDetectorAlerts } = useValues(logic)
    const { setShowAlertAnomalyPoints } = useActions(logic)

    if (!hasDetectorAlerts) {
        return null
    }

    return (
        <OptionSwitchRow
            id="insight-option-alert-anomaly-points"
            label="Show alert anomaly points"
            checked={showAlertAnomalyPointsFlag}
            onCheckedChange={() => setShowAlertAnomalyPoints(!showAlertAnomalyPointsFlag)}
        />
    )
}

function MultipleYAxesNext(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { showMultipleYAxes } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    return (
        <OptionSwitchRow
            id="insight-option-multiple-y-axes"
            label="Show multiple Y-axes"
            checked={!!showMultipleYAxes}
            onCheckedChange={() => updateInsightFilter({ showMultipleYAxes: !showMultipleYAxes })}
        />
    )
}

function TrendLinesNext(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { querySource, trendsFilter, yAxisScaleType } = useValues(insightVizDataLogic(insightProps))
    const { isTrendsFunnel } = useValues(funnelDataLogic(insightProps))
    const { updateQuerySource } = useActions(insightVizDataLogic(insightProps))

    const showTrendLines = isRetentionQuery(querySource)
        ? querySource.retentionFilter.showTrendLines
        : isTrendsQuery(querySource)
          ? querySource.trendsFilter?.showTrendLines
          : isFunnelsQuery(querySource)
            ? querySource.funnelsFilter?.showTrendLines
            : false

    const isLinearScale = !yAxisScaleType || yAxisScaleType === 'linear'
    const isLineGraph = isTrendsQuery(querySource)
        ? (trendsFilter?.display || ChartDisplayType.ActionsLineGraph) === ChartDisplayType.ActionsLineGraph ||
          (trendsFilter?.display || ChartDisplayType.ActionsLineGraph) === ChartDisplayType.ActionsLineGraphCumulative
        : isFunnelsQuery(querySource)
          ? isTrendsFunnel
          : true // Retention graphs are always line graphs

    const disabledReason = !isLineGraph
        ? 'Trend lines are only available for line graphs'
        : !isLinearScale
          ? 'Trend lines are only supported for linear scale.'
          : undefined

    const toggleShowTrendLines = (): void => {
        if (isRetentionQuery(querySource)) {
            updateQuerySource({
                retentionFilter: { ...querySource.retentionFilter, showTrendLines: !showTrendLines },
            } as any)
        } else if (isTrendsQuery(querySource)) {
            updateQuerySource({ trendsFilter: { ...querySource.trendsFilter, showTrendLines: !showTrendLines } } as any)
        } else if (isFunnelsQuery(querySource)) {
            updateQuerySource({
                funnelsFilter: { ...querySource.funnelsFilter, showTrendLines: !showTrendLines },
            } as any)
        }
    }

    return (
        <OptionSwitchRow
            id="insight-option-trend-lines"
            label="Show trend lines"
            checked={!disabledReason && !!showTrendLines}
            onCheckedChange={toggleShowTrendLines}
            disabledReason={disabledReason}
        />
    )
}

function HideIncompleteFunnelPeriodsNext(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { querySource } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    if (!isFunnelsQuery(querySource)) {
        return null
    }

    const hideIncompleteConversionWindowPeriods =
        querySource.funnelsFilter?.hideIncompleteConversionWindowPeriods ?? false

    return (
        <OptionSwitchRow
            id="insight-option-hide-incomplete-periods"
            label="Hide incomplete periods"
            tooltip="Hides recent periods whose conversion window hasn't fully elapsed, so the trend isn't dragged down by entrants who still have time to convert."
            checked={hideIncompleteConversionWindowPeriods}
            onCheckedChange={() =>
                updateInsightFilter({ hideIncompleteConversionWindowPeriods: !hideIncompleteConversionWindowPeriods })
            }
        />
    )
}

function HideWeekendsNext(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { trendsFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    return (
        <OptionSwitchRow
            id="insight-option-hide-weekends"
            label="Hide weekend data"
            checked={!!trendsFilter?.hideWeekends}
            onCheckedChange={() => updateInsightFilter({ hideWeekends: !trendsFilter?.hideWeekends })}
        />
    )
}

function AnnotationsNext(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { showAnnotations } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    return (
        <OptionSwitchRow
            id="insight-option-annotations"
            label="Show annotations"
            checked={showAnnotations !== false}
            onCheckedChange={(checked) => updateInsightFilter({ showAnnotations: checked })}
        />
    )
}

function ResultCustomizationByNext(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { resultCustomizationBy } = useValues(trendsDataLogic(insightProps))
    const { updateInsightFilter } = useActions(trendsDataLogic(insightProps))

    return (
        <div className="px-3 py-1">
            <ToggleGroup size="sm" className="w-full" value={[resultCustomizationBy]}>
                {[
                    { value: ResultCustomizationBy.Value, label: 'By name' },
                    { value: ResultCustomizationBy.Position, label: 'By rank' },
                ].map((option) => (
                    <ToggleGroupItem
                        key={option.value}
                        value={option.value}
                        className="flex-1"
                        onClick={() => updateInsightFilter({ resultCustomizationBy: option.value })}
                    >
                        {option.label}
                    </ToggleGroupItem>
                ))}
            </ToggleGroup>
        </div>
    )
}

function UnitNext(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { trendsFilter, display } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))
    const { showCustomUnitModal } = useActions(unitPickerModalLogic)
    const { reportAxisUnitsChanged } = useActions(eventUsageLogic)

    const [open, setOpen] = useState(false)
    const [localAxisFormat, setLocalAxisFormat] = useState(trendsFilter?.aggregationAxisFormat || undefined)
    // Some display types (e.g. Metric) render a default unit when none is explicitly set — reflect it here.
    const effectiveAxisFormat = localAxisFormat ?? defaultAggregationAxisFormatForDisplay(display)

    const handleChange = ({
        format,
        prefix,
        postfix,
    }: {
        format?: AggregationAxisFormat
        prefix?: string
        postfix?: string
    }): void => {
        setLocalAxisFormat(format)
        updateInsightFilter({
            aggregationAxisFormat: format,
            aggregationAxisPrefix: prefix,
            aggregationAxisPostfix: postfix,
        })
        reportAxisUnitsChanged({
            format,
            prefix,
            postfix,
            display,
            unitIsSet: !!prefix || !!postfix || (format && format !== 'numeric'),
        })
        setOpen(false)
    }

    const displayValue = useMemo(() => {
        let displayValue: ReactNode = 'None'
        if (effectiveAxisFormat) {
            displayValue = INSIGHT_UNIT_OPTIONS_SHORT[effectiveAxisFormat]
        }
        if (trendsFilter?.aggregationAxisPrefix?.length) {
            displayValue = `Prefix: ${trendsFilter?.aggregationAxisPrefix}`
        }
        if (trendsFilter?.aggregationAxisPostfix?.length) {
            displayValue = `Postfix: ${trendsFilter?.aggregationAxisPostfix}`
        }
        return displayValue
    }, [effectiveAxisFormat, trendsFilter])

    return (
        <div className="px-3 py-1">
            <Popover open={open} onOpenChange={setOpen}>
                <PopoverTrigger
                    render={
                        <Button
                            variant="outline"
                            size="sm"
                            left
                            className="w-full"
                            data-attr="chart-aggregation-axis-format"
                        />
                    }
                >
                    <span className="min-w-0 truncate">{displayValue}</span>
                </PopoverTrigger>
                <PopoverContent align="start" className="w-56 p-0">
                    <div className="flex flex-col gap-px p-2">
                        {INSIGHT_UNIT_OPTIONS.map(({ value, label }) => (
                            <Button
                                key={value}
                                variant="default"
                                size="sm"
                                left
                                className="w-full justify-start"
                                aria-selected={value === effectiveAxisFormat}
                                onClick={() => handleChange({ format: value })}
                            >
                                {label}
                            </Button>
                        ))}
                        <Separator className="my-1" />
                        <Button
                            variant="default"
                            size="sm"
                            left
                            className="w-full justify-start"
                            aria-selected={!!trendsFilter?.aggregationAxisPrefix}
                            onClick={() =>
                                showCustomUnitModal({
                                    type: 'prefix',
                                    currentValue: trendsFilter?.aggregationAxisPrefix || '',
                                    callback: (value: string) => handleChange({ prefix: value }),
                                })
                            }
                        >
                            Custom prefix
                            {trendsFilter?.aggregationAxisPrefix
                                ? `: ${trendsFilter?.aggregationAxisPrefix}...`
                                : '...'}
                        </Button>
                        <Button
                            variant="default"
                            size="sm"
                            left
                            className="w-full justify-start"
                            aria-selected={!!trendsFilter?.aggregationAxisPostfix}
                            onClick={() =>
                                showCustomUnitModal({
                                    type: 'postfix',
                                    currentValue: trendsFilter?.aggregationAxisPostfix || '',
                                    callback: (value: string) => handleChange({ postfix: value }),
                                })
                            }
                        >
                            Custom postfix
                            {trendsFilter?.aggregationAxisPostfix
                                ? `: ${trendsFilter?.aggregationAxisPostfix}...`
                                : '...'}
                        </Button>
                    </div>
                </PopoverContent>
            </Popover>
        </div>
    )
}

function ScaleNext(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { yAxisScaleType } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    return (
        <div className="px-3 py-1">
            <ToggleGroup size="sm" className="w-full" value={[yAxisScaleType || 'linear']}>
                {[
                    { value: 'linear', label: 'Linear' },
                    { value: 'log10', label: 'Logarithmic' },
                ].map((option) => (
                    <ToggleGroupItem
                        key={option.value}
                        value={option.value}
                        className="flex-1"
                        onClick={() => updateInsightFilter({ yAxisScaleType: option.value as 'linear' | 'log10' })}
                    >
                        {option.label}
                    </ToggleGroupItem>
                ))}
            </ToggleGroup>
        </div>
    )
}

function ConfidenceIntervalNext(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { querySource, trendsFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateQuerySource } = useActions(insightVizDataLogic(insightProps))
    const { showConfidenceIntervals } = useValues(trendsDataLogic(insightProps))
    const { isLineGraph, isLinearScale } = useLineGraphState()

    return (
        <OptionSwitchRow
            id="insight-option-confidence-intervals"
            label="Show confidence intervals"
            checked={showConfidenceIntervals}
            disabledReason={
                !isLineGraph
                    ? 'Confidence intervals are only available for line graphs'
                    : !isLinearScale
                      ? 'Confidence intervals are only supported for linear scale.'
                      : undefined
            }
            onCheckedChange={(checked) => {
                if (isTrendsQuery(querySource)) {
                    updateQuerySource({
                        ...querySource,
                        trendsFilter: { ...trendsFilter, showConfidenceIntervals: checked },
                    })
                }
            }}
        />
    )
}

function ConfidenceLevelNext(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { confidenceLevel, showConfidenceIntervals } = useValues(trendsDataLogic(insightProps))
    const { querySource } = useValues(insightVizDataLogic(insightProps))
    const { updateQuerySource } = useActions(insightVizDataLogic(insightProps))
    const trendsFilter = isTrendsQuery(querySource) ? querySource.trendsFilter : undefined

    const [localValue, setLocalValue] = useState(confidenceLevel)

    useEffect(() => {
        setLocalValue(confidenceLevel)
    }, [confidenceLevel])

    const debouncedUpdate = useDebouncedCallback((value: number) => {
        if (isTrendsQuery(querySource)) {
            updateQuerySource({ ...querySource, trendsFilter: { ...trendsFilter, confidenceLevel: value } })
        }
    }, 500)

    return (
        <div className="flex items-center justify-between gap-2 py-1.5 pr-3 pl-6">
            <span className="flex items-center gap-1 font-normal">
                Confidence level
                <OptionTooltip>
                    A 95% confidence level means that for each data point, we are 95% confident that the true value is
                    within the confidence interval.
                </OptionTooltip>
            </span>
            <div
                className="flex items-center gap-1"
                title={!showConfidenceIntervals ? 'Confidence intervals are only available for line graphs' : undefined}
            >
                <Input
                    type="number"
                    className="h-6 w-16"
                    min={0}
                    max={100}
                    step={1}
                    value={localValue}
                    disabled={!showConfidenceIntervals}
                    aria-label="Confidence level"
                    onChange={(e: ChangeEvent<HTMLInputElement>) => {
                        const numValue = e.target.value === '' ? 95 : Number(e.target.value)
                        setLocalValue(numValue)
                        debouncedUpdate(numValue)
                    }}
                />
                <span className="text-xs">%</span>
            </div>
        </div>
    )
}

function MovingAverageNext(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { querySource, trendsFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateQuerySource } = useActions(insightVizDataLogic(insightProps))
    const { showMovingAverage } = useValues(trendsDataLogic(insightProps))
    const { isLineGraph, isLinearScale } = useLineGraphState()

    return (
        <OptionSwitchRow
            id="insight-option-moving-average"
            label="Show moving average"
            checked={showMovingAverage}
            disabledReason={
                !isLineGraph
                    ? 'Moving average is only available for line and area graphs'
                    : !isLinearScale
                      ? 'Moving average is only supported for linear scale.'
                      : undefined
            }
            onCheckedChange={(checked) => {
                if (isTrendsQuery(querySource)) {
                    updateQuerySource({ ...querySource, trendsFilter: { ...trendsFilter, showMovingAverage: checked } })
                }
            }}
        />
    )
}

function MovingAverageIntervalsNext(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { movingAverageIntervals, showMovingAverage } = useValues(trendsDataLogic(insightProps))
    const { querySource } = useValues(insightVizDataLogic(insightProps))
    const { updateQuerySource } = useActions(insightVizDataLogic(insightProps))
    const trendsFilter = isTrendsQuery(querySource) ? querySource.trendsFilter : undefined

    const [localValue, setLocalValue] = useState(movingAverageIntervals)

    useEffect(() => {
        setLocalValue(movingAverageIntervals)
    }, [movingAverageIntervals])

    const debouncedUpdate = useDebouncedCallback((value: number) => {
        if (isTrendsQuery(querySource)) {
            updateQuerySource({ ...querySource, trendsFilter: { ...trendsFilter, movingAverageIntervals: value } })
        }
    }, 500)

    const interval = isTrendsQuery(querySource) ? querySource.interval || 'day' : 'day'

    return (
        <div className="flex items-center justify-between gap-2 py-1.5 pr-3 pl-6">
            <span className="flex items-center gap-1 font-normal">
                Intervals
                <OptionTooltip>
                    The number of data points to use for calculating the moving average. A larger number will create a
                    smoother line but with more lag. You can't use a number greater than the amount of intervals in your
                    date range.
                </OptionTooltip>
            </span>
            <div
                className="flex items-center gap-1"
                title={!showMovingAverage ? 'Moving averages are only available for line and area graphs' : undefined}
            >
                <Input
                    type="number"
                    className="h-6 w-16"
                    min={2}
                    step={1}
                    value={localValue}
                    disabled={!showMovingAverage}
                    aria-label="Moving average intervals"
                    onChange={(e: ChangeEvent<HTMLInputElement>) => {
                        const numValue =
                            e.target.value === ''
                                ? INTERVAL_TO_DEFAULT_MOVING_AVERAGE_PERIOD[interval]
                                : Number(e.target.value)
                        setLocalValue(numValue)
                        debouncedUpdate(numValue)
                    }}
                />
                <span className="text-xs whitespace-nowrap">{`${interval}s`}</span>
            </div>
        </div>
    )
}

function AxisLabelsNext(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { trendsFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))
    const [xAxisLabelDraft, setXAxisLabelDraft] = useState(trendsFilter?.xAxisLabel ?? '')
    const [yAxisLabelDraft, setYAxisLabelDraft] = useState(trendsFilter?.yAxisLabel ?? '')

    useEffect(() => {
        setXAxisLabelDraft(trendsFilter?.xAxisLabel ?? '')
    }, [trendsFilter?.xAxisLabel])

    useEffect(() => {
        setYAxisLabelDraft(trendsFilter?.yAxisLabel ?? '')
    }, [trendsFilter?.yAxisLabel])

    const commitXAxisLabel = (): void => {
        const normalized = normalizeAxisLabel(xAxisLabelDraft)
        setXAxisLabelDraft(normalized ?? '')
        updateInsightFilter({ xAxisLabel: normalized })
    }

    const commitYAxisLabel = (): void => {
        const normalized = normalizeAxisLabel(yAxisLabelDraft)
        setYAxisLabelDraft(normalized ?? '')
        updateInsightFilter({ yAxisLabel: normalized })
    }

    return (
        <div className="flex flex-col gap-2 px-3 py-1">
            <div className="flex flex-col gap-1">
                <Label htmlFor="insight-option-x-axis-label">X-axis label</Label>
                <Input
                    id="insight-option-x-axis-label"
                    data-attr="trends-x-axis-label-input"
                    value={xAxisLabelDraft}
                    placeholder="X-axis label"
                    onChange={(e: ChangeEvent<HTMLInputElement>) => setXAxisLabelDraft(e.target.value)}
                    onBlur={commitXAxisLabel}
                    onKeyDown={(e: KeyboardEvent<HTMLInputElement>) => e.key === 'Enter' && commitXAxisLabel()}
                />
            </div>
            <div className="flex flex-col gap-1">
                <Label htmlFor="insight-option-y-axis-label">Y-axis label</Label>
                <Input
                    id="insight-option-y-axis-label"
                    data-attr="trends-y-axis-label-input"
                    value={yAxisLabelDraft}
                    placeholder="Y-axis label"
                    onChange={(e: ChangeEvent<HTMLInputElement>) => setYAxisLabelDraft(e.target.value)}
                    onBlur={commitYAxisLabel}
                    onKeyDown={(e: KeyboardEvent<HTMLInputElement>) => e.key === 'Enter' && commitYAxisLabel()}
                />
            </div>
        </div>
    )
}

function DecimalPrecisionNext(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { trendsFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    const reportChange = useDebouncedCallback(() => {
        posthog.capture('decimal places changed', {
            decimal_places: trendsFilter?.decimalPlaces,
        })
    }, 500)

    return (
        <div className="px-3 py-1">
            <Input
                type="number"
                step={1}
                min={0}
                max={9}
                value={trendsFilter?.decimalPlaces ?? DEFAULT_DECIMAL_PLACES}
                aria-label="Decimal places"
                onChange={(e: ChangeEvent<HTMLInputElement>) => {
                    const parsed = parseInt(e.target.value)
                    updateInsightFilter({ decimalPlaces: Number.isNaN(parsed) ? undefined : parsed })
                    reportChange()
                }}
            />
        </div>
    )
}

function RetentionDashboardDisplayNext(): JSX.Element | null {
    const { insightProps, canEditInsight } = useValues(insightLogic)
    const { retentionFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    if (!canEditInsight) {
        return null
    }

    const options = [
        { value: RetentionDashboardDisplayType.TableOnly, label: 'Show table only' },
        { value: RetentionDashboardDisplayType.GraphOnly, label: 'Show graph only' },
        { value: RetentionDashboardDisplayType.All, label: 'Show both' },
    ]

    return (
        <div className="px-3 py-1">
            <Select
                value={retentionFilter?.dashboardDisplay || RetentionDashboardDisplayType.TableOnly}
                items={Object.fromEntries(options.map((option) => [option.value, option.label]))}
                onValueChange={(value: string | null) => {
                    if (value) {
                        updateInsightFilter({ dashboardDisplay: value as RetentionDashboardDisplayType })
                    }
                }}
            >
                <SelectTrigger size="sm" className="w-full">
                    <SelectValue />
                </SelectTrigger>
                <SelectContent>
                    {options.map((option) => (
                        <SelectItem key={option.value} value={option.value}>
                            {option.label}
                        </SelectItem>
                    ))}
                </SelectContent>
            </Select>
        </div>
    )
}

function RetentionCohortLabelStartNext(): JSX.Element | null {
    const { insightProps, canEditInsight } = useValues(insightLogic)
    const { retentionFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    if (!canEditInsight) {
        return null
    }

    const period = retentionFilter?.period || 'Day'

    return (
        <div className="px-3 py-1">
            <ToggleGroup size="sm" className="w-full" value={[String(retentionFilter?.cohortLabelStartIndex ?? 0)]}>
                {[0, 1].map((index) => (
                    <ToggleGroupItem
                        key={index}
                        value={String(index)}
                        className="flex-1"
                        onClick={() => updateInsightFilter({ cohortLabelStartIndex: index })}
                    >
                        {`${period} ${index}`}
                    </ToggleGroupItem>
                ))}
            </ToggleGroup>
        </div>
    )
}

// Quill twins of `DisplayOptions`, keyed identically so both shells consume the same
// `useInsightDisplayOptionSections()` structure.
export const DisplayOptionsNext: Record<DisplayOptionKey, () => JSX.Element | null> = {
    Smoothing: SmoothingNext,
    Legend: LegendNext,
    LegendOptions: LegendOptionsNext,
    ExcludeOutliers: ExcludeOutliersNext,
    MetricSummary: MetricSummaryNext,
    MetricShowChange: MetricShowChangeNext,
    MetricColor: MetricColorNext,
    LifecycleStacking: LifecycleStackingNext,
    LifecyclePercentages: LifecyclePercentagesNext,
    ValueLabels: ValueLabelsNext,
    PercentStack: PercentStackNext,
    StackBreakdown: StackBreakdownNext,
    PieTotal: PieTotalNext,
    AlertThresholdLines: AlertThresholdLinesNext,
    AlertAnomalyPoints: AlertAnomalyPointsNext,
    MultipleYAxes: MultipleYAxesNext,
    TrendLines: TrendLinesNext,
    HideIncompleteFunnelPeriods: HideIncompleteFunnelPeriodsNext,
    HideWeekends: HideWeekendsNext,
    Annotations: AnnotationsNext,
    ResultCustomizationBy: ResultCustomizationByNext,
    Unit: UnitNext,
    Scale: ScaleNext,
    ConfidenceInterval: ConfidenceIntervalNext,
    ConfidenceLevel: ConfidenceLevelNext,
    MovingAverage: MovingAverageNext,
    MovingAverageIntervals: MovingAverageIntervalsNext,
    AxisLabels: AxisLabelsNext,
    DecimalPrecision: DecimalPrecisionNext,
    RetentionDashboardDisplay: RetentionDashboardDisplayNext,
    RetentionCohortLabelStart: RetentionCohortLabelStartNext,
}
