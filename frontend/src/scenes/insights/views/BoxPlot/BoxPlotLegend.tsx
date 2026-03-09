import clsx from 'clsx'
import { useValues } from 'kea'

import 'lib/components/InsightLegend/InsightLegend.scss'
import { getSeriesColor } from 'lib/colors'
import { insightLogic } from 'scenes/insights/insightLogic'

import { boxPlotChartLogic } from './boxPlotChartLogic'

export interface BoxPlotLegendProps {
    horizontal?: boolean
    inCardView?: boolean
}

export function BoxPlotLegend({ horizontal, inCardView }: BoxPlotLegendProps): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { seriesGroups } = useValues(boxPlotChartLogic(insightProps))

    if (seriesGroups.length === 0) {
        return null
    }

    return (
        <div
            className={clsx('InsightLegendMenu', 'flex overflow-auto border rounded', {
                'InsightLegendMenu--horizontal': horizontal,
                'InsightLegendMenu--readonly': true,
                'InsightLegendMenu--in-card-view': inCardView,
            })}
        >
            <div className="grid grid-cols-1">
                {seriesGroups.map((group) => (
                    <div
                        key={group.seriesIndex}
                        className="InsightLegendMenu-item p-2 flex flex-row items-center gap-2 whitespace-nowrap"
                    >
                        <span
                            className="w-3 h-3 rounded-full inline-block shrink-0"
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{ backgroundColor: getSeriesColor(group.seriesIndex) }}
                        />
                        <span className="text-xs">{group.seriesLabel}</span>
                    </div>
                ))}
            </div>
        </div>
    )
}
