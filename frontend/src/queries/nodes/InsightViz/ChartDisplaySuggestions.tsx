import { useActions, useValues } from 'kea'

import { IconGlobe, IconGraph, IconPieChart, IconTrends } from '@posthog/icons'

import { dataColorVars } from 'lib/colors'
import { Sparkline, SparklineTimeSeries } from 'lib/components/Sparkline'
import { FEATURE_FLAGS } from 'lib/constants'
import { Icon123, IconAreaChart } from 'lib/lemon-ui/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { trendsDataLogic } from 'scenes/trends/trendsDataLogic'

import { ChartDisplayType } from '~/types'

const MAX_PREVIEW_SERIES = 3
const MAX_PREVIEW_POINTS = 16

/** Thin long series so every thumbnail stays within Sparkline's medium width bucket. */
function downsample(values: number[]): number[] {
    if (values.length <= MAX_PREVIEW_POINTS) {
        return values
    }
    const step = values.length / MAX_PREVIEW_POINTS
    return Array.from({ length: MAX_PREVIEW_POINTS }, (_, i) => values[Math.floor(i * step)])
}

interface DisplaySuggestion {
    value: ChartDisplayType
    label: string
    /** When set, the thumbnail is a live Sparkline of the fetched results instead of the icon. */
    previewType?: 'line' | 'bar'
    icon: JSX.Element
}

export function ChartDisplaySuggestions(): JSX.Element | null {
    const { insightProps, canEditInsight } = useValues(insightLogic)
    const { display, isTrends, isSingleSeriesOutput, formula, breakdownFilter, insightDataLoading } = useValues(
        insightVizDataLogic(insightProps)
    )
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))
    const { indexedResults } = useValues(trendsDataLogic(insightProps))
    const { featureFlags } = useValues(featureFlagLogic)

    if (
        !featureFlags[FEATURE_FLAGS.INSIGHT_CHART_SUGGESTIONS] ||
        !isTrends ||
        !canEditInsight ||
        insightDataLoading ||
        indexedResults.length === 0
    ) {
        return null
    }

    const currentDisplay = display || ChartDisplayType.ActionsLineGraph

    const previewSeries: SparklineTimeSeries[] = indexedResults
        .slice(0, MAX_PREVIEW_SERIES)
        .map((result, index) => ({
            name: result.label,
            values: downsample(result.data ?? []),
            color: dataColorVars[index % dataColorVars.length],
        }))
        .filter((series) => series.values.length > 1)
    // Total value displays return one aggregate per series, not day-by-day data, so
    // there is nothing to draw a live time series thumbnail from.
    const hasTimeSeriesData = previewSeries.length > 0

    const isCountryBreakdown =
        breakdownFilter?.breakdown === '$geoip_country_code' || breakdownFilter?.breakdown === '$geoip_country_name'

    const suggestions: DisplaySuggestion[] = [
        {
            value: ChartDisplayType.ActionsLineGraph,
            label: 'Line chart',
            previewType: 'line' as const,
            icon: <IconTrends />,
        },
        {
            value: ChartDisplayType.ActionsUnstackedBar,
            label: 'Bar chart',
            previewType: 'bar' as const,
            icon: <IconGraph />,
        },
        {
            value: ChartDisplayType.ActionsAreaGraph,
            label: 'Area chart',
            previewType: 'line' as const,
            icon: <IconAreaChart />,
        },
        ...(isSingleSeriesOutput
            ? [
                  {
                      value: ChartDisplayType.BoldNumber,
                      label: 'Number',
                      icon: <Icon123 />,
                  },
              ]
            : []),
        ...(isSingleSeriesOutput && featureFlags[FEATURE_FLAGS.METRIC_INSIGHT]
            ? [
                  {
                      value: ChartDisplayType.Metric,
                      label: 'Metric',
                      icon: <IconTrends />,
                  },
              ]
            : []),
        {
            value: ChartDisplayType.ActionsPie,
            label: 'Pie chart',
            icon: <IconPieChart />,
        },
        ...(isCountryBreakdown && !formula
            ? [
                  {
                      value: ChartDisplayType.WorldMap,
                      label: 'World map',
                      icon: <IconGlobe />,
                  },
              ]
            : []),
    ].filter((suggestion) => suggestion.value !== currentDisplay)

    if (suggestions.length === 0) {
        return null
    }

    return (
        <div className="flex items-center gap-2 flex-wrap border-t px-4 py-2" data-attr="chart-display-suggestions">
            <span className="text-xs text-secondary shrink-0">View as</span>
            {suggestions.map((suggestion) => (
                <button
                    key={suggestion.value}
                    type="button"
                    className="flex flex-col items-center justify-end gap-1 min-w-24 px-3 py-1.5 border rounded bg-surface-primary cursor-pointer hover:border-accent transition-colors"
                    onClick={() => updateInsightFilter({ display: suggestion.value })}
                    data-attr={`chart-display-suggestion-${suggestion.value}`}
                >
                    <div className="h-8 flex items-center justify-center pointer-events-none">
                        {suggestion.previewType && hasTimeSeriesData ? (
                            <Sparkline
                                data={previewSeries}
                                type={suggestion.previewType}
                                maximumIndicator={false}
                                className="h-8"
                            />
                        ) : (
                            <span className="text-xl text-secondary">{suggestion.icon}</span>
                        )}
                    </div>
                    <span className="text-xs">{suggestion.label}</span>
                </button>
            ))}
        </div>
    )
}
