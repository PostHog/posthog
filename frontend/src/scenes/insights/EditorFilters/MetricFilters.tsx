import { useActions, useValues } from 'kea'

import { getSeriesColorPalette } from 'lib/colors'
import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { LemonColorPicker } from 'lib/lemon-ui/LemonColor'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { METRIC_DEFAULT_BAD_COLOR, METRIC_DEFAULT_GOOD_COLOR } from 'scenes/insights/views/Metric/Metric'

import { insightLogic } from '../insightLogic'

export function MetricGoodDirectionFilter(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { trendsFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    const higherIsBetter = (trendsFilter?.metricGoodDirection ?? 'up') === 'up'

    return (
        <LemonCheckbox
            className="p-1 px-2"
            checked={higherIsBetter}
            onChange={() => updateInsightFilter({ metricGoodDirection: higherIsBetter ? 'down' : 'up' })}
            label={<span className="font-normal">Higher is better</span>}
            size="small"
        />
    )
}

export function MetricShowChangeFilter(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { trendsFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    const checked = trendsFilter?.metricShowChange ?? true

    return (
        <LemonCheckbox
            className="p-1 px-2"
            checked={checked}
            onChange={() => updateInsightFilter({ metricShowChange: !checked })}
            label={<span className="font-normal">Show change</span>}
            size="small"
        />
    )
}

export function MetricColorFilter(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { trendsFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    const colorByDirection = trendsFilter?.metricColorByDirection ?? false
    const goodColor = trendsFilter?.metricGoodColor ?? METRIC_DEFAULT_GOOD_COLOR
    const badColor = trendsFilter?.metricBadColor ?? METRIC_DEFAULT_BAD_COLOR
    const presetColors = getSeriesColorPalette()

    return (
        <div className="flex flex-col">
            <LemonCheckbox
                className="p-1 px-2"
                checked={colorByDirection}
                onChange={() => updateInsightFilter({ metricColorByDirection: !colorByDirection })}
                label={<span className="font-normal">Color line by trend</span>}
                size="small"
            />
            {colorByDirection && (
                <div className="flex flex-col gap-1 p-1 px-2 pl-7">
                    <div className="flex items-center justify-between gap-2">
                        <span className="font-normal">Improving</span>
                        <LemonColorPicker
                            colors={presetColors}
                            selectedColor={goodColor}
                            onSelectColor={(color) => updateInsightFilter({ metricGoodColor: color })}
                            showCustomColor
                            preventPopoverClose
                        />
                    </div>
                    <div className="flex items-center justify-between gap-2">
                        <span className="font-normal">Declining</span>
                        <LemonColorPicker
                            colors={presetColors}
                            selectedColor={badColor}
                            onSelectColor={(color) => updateInsightFilter({ metricBadColor: color })}
                            showCustomColor
                            preventPopoverClose
                        />
                    </div>
                </div>
            )}
        </div>
    )
}
