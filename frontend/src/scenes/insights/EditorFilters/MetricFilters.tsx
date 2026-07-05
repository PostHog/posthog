import { useActions, useValues } from 'kea'

import { LemonSelect } from '@posthog/lemon-ui'

import { getSeriesColorPalette } from 'lib/colors'
import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { LemonColorPicker } from 'lib/lemon-ui/LemonColor'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import {
    METRIC_COLOR_BY_DIRECTION_DEFAULT,
    METRIC_DEFAULT_DECREASE_COLOR,
    METRIC_DEFAULT_INCREASE_COLOR,
    METRIC_SHOW_CHANGE_DEFAULT,
    METRIC_SUMMARY_DEFAULT,
    type MetricSummary,
} from 'scenes/insights/views/Metric/Metric.utils'

import { insightLogic } from '../insightLogic'

const PRESET_COLORS = getSeriesColorPalette()

export function DirectionColorPickers({
    increaseColor,
    decreaseColor,
    onIncrease,
    onDecrease,
}: {
    increaseColor: string
    decreaseColor: string
    onIncrease: (color: string) => void
    onDecrease: (color: string) => void
}): JSX.Element {
    return (
        <div className="flex flex-col gap-1 pl-5">
            <div className="flex items-center justify-between gap-2 p-1 px-2">
                <span className="font-normal">Increase</span>
                <LemonColorPicker
                    colors={PRESET_COLORS}
                    selectedColor={increaseColor}
                    onSelectColor={onIncrease}
                    showCustomColor
                    preventPopoverClose
                />
            </div>
            <div className="flex items-center justify-between gap-2 p-1 px-2">
                <span className="font-normal">Decrease</span>
                <LemonColorPicker
                    colors={PRESET_COLORS}
                    selectedColor={decreaseColor}
                    onSelectColor={onDecrease}
                    showCustomColor
                    preventPopoverClose
                />
            </div>
        </div>
    )
}

export function MetricSummaryFilter(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { trendsFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    const summary = trendsFilter?.metricSummary ?? METRIC_SUMMARY_DEFAULT

    return (
        <div className="flex items-center justify-between gap-2 p-1 px-2">
            <span className="font-normal">Headline value</span>
            <LemonSelect<MetricSummary>
                size="small"
                value={summary}
                onChange={(value) => updateInsightFilter({ metricSummary: value })}
                options={[
                    { value: 'total', label: 'Total' },
                    { value: 'average', label: 'Average' },
                    { value: 'latest', label: 'Latest' },
                ]}
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
            <LemonCheckbox
                className="p-1 px-2"
                checked={showChange}
                onChange={() => updateInsightFilter({ metricShowChange: !showChange })}
                label={<span className="font-normal">Show change</span>}
                size="small"
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

export function MetricColorFilter(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { trendsFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    const colorByDirection = trendsFilter?.metricColorByDirection ?? METRIC_COLOR_BY_DIRECTION_DEFAULT

    return (
        <div className="flex flex-col">
            <LemonCheckbox
                className="p-1 px-2"
                checked={colorByDirection}
                onChange={() => updateInsightFilter({ metricColorByDirection: !colorByDirection })}
                label={<span className="font-normal">Color by trend</span>}
                size="small"
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
