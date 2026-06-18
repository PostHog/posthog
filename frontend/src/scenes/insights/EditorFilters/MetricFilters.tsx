import { useActions, useValues } from 'kea'

import { getSeriesColorPalette } from 'lib/colors'
import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { LemonColorPicker } from 'lib/lemon-ui/LemonColor'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { METRIC_DEFAULT_DECREASE_COLOR, METRIC_DEFAULT_INCREASE_COLOR } from 'scenes/insights/views/Metric/Metric'

import { insightLogic } from '../insightLogic'

const PRESET_COLORS = getSeriesColorPalette()

function DirectionColorPickers({
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

export function MetricShowChangeFilter(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { trendsFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    const showChange = trendsFilter?.metricShowChange ?? true

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

    const colorByDirection = trendsFilter?.metricColorByDirection ?? false

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
