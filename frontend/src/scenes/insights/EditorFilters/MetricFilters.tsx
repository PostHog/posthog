import { useActions, useValues } from 'kea'

import { LemonSelect } from '@posthog/lemon-ui'
import { Text } from '@posthog/quill'

import { MetricDirectionColorPickers } from 'lib/components/Metric/MetricDirectionColorPickers'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { DisplayOptionCheckbox } from '~/queries/nodes/InsightViz/DisplayOptionCheckbox'
import { QuillDisplayOptionSelect } from '~/queries/nodes/InsightViz/QuillDisplayOptionSelect'

import {
    METRIC_COLOR_BY_DIRECTION_DEFAULT,
    METRIC_DEFAULT_DECREASE_COLOR,
    METRIC_DEFAULT_INCREASE_COLOR,
    METRIC_SHOW_CHANGE_DEFAULT,
    METRIC_SUMMARY_DEFAULT,
    type MetricSummary,
} from 'products/product_analytics/frontend/insights/trends/Metric/Metric.utils'

import { insightLogic } from '../insightLogic'

const METRIC_SUMMARY_OPTIONS: { value: MetricSummary; label: string }[] = [
    { value: 'total', label: 'Total' },
    { value: 'average', label: 'Average' },
    { value: 'latest', label: 'Latest' },
]

export function MetricSummaryFilter(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { trendsFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const summary = trendsFilter?.metricSummary ?? METRIC_SUMMARY_DEFAULT
    const onSummaryChange = (value: MetricSummary): void => updateInsightFilter({ metricSummary: value })

    if (todayRailNav) {
        return (
            <div className="flex items-center justify-between gap-2">
                <Text size="xs" render={<span />}>
                    Headline value
                </Text>
                <QuillDisplayOptionSelect value={summary} onChange={onSummaryChange} options={METRIC_SUMMARY_OPTIONS} />
            </div>
        )
    }

    return (
        <div className="flex items-center justify-between gap-2 p-1 px-2">
            <span className="font-normal">Headline value</span>
            <LemonSelect<MetricSummary>
                size="small"
                value={summary}
                onChange={onSummaryChange}
                options={METRIC_SUMMARY_OPTIONS}
            />
        </div>
    )
}

export function MetricShowChangeFilter(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { trendsFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    const showChange = trendsFilter?.metricShowChange ?? METRIC_SHOW_CHANGE_DEFAULT

    return (
        <div className="flex flex-col">
            <DisplayOptionCheckbox
                label="Show change"
                checked={showChange}
                onChange={() => updateInsightFilter({ metricShowChange: !showChange })}
            />
            {showChange && (
                <MetricDirectionColorPickers
                    className="gap-1 pl-5"
                    rowClassName="p-1 px-2"
                    increaseColor={trendsFilter?.metricChangeIncreaseColor ?? METRIC_DEFAULT_INCREASE_COLOR}
                    decreaseColor={trendsFilter?.metricChangeDecreaseColor ?? METRIC_DEFAULT_DECREASE_COLOR}
                    onIncrease={(color) => updateInsightFilter({ metricChangeIncreaseColor: color })}
                    onDecrease={(color) => updateInsightFilter({ metricChangeDecreaseColor: color })}
                />
            )}
        </div>
    )
}

export function MetricColorFilter(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { trendsFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    const colorByDirection = trendsFilter?.metricColorByDirection ?? METRIC_COLOR_BY_DIRECTION_DEFAULT

    return (
        <div className="flex flex-col">
            <DisplayOptionCheckbox
                label="Color by trend"
                checked={colorByDirection}
                onChange={() => updateInsightFilter({ metricColorByDirection: !colorByDirection })}
            />
            {colorByDirection && (
                <MetricDirectionColorPickers
                    className="gap-1 pl-5"
                    rowClassName="p-1 px-2"
                    increaseColor={trendsFilter?.metricLineIncreaseColor ?? METRIC_DEFAULT_INCREASE_COLOR}
                    decreaseColor={trendsFilter?.metricLineDecreaseColor ?? METRIC_DEFAULT_DECREASE_COLOR}
                    onIncrease={(color) => updateInsightFilter({ metricLineIncreaseColor: color })}
                    onDecrease={(color) => updateInsightFilter({ metricLineDecreaseColor: color })}
                />
            )}
        </div>
    )
}
