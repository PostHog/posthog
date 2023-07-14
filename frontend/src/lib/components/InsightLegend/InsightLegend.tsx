import './InsightLegend.scss'
import { useActions, useValues } from 'kea'
import { insightLogic } from 'scenes/insights/insightLogic'
import clsx from 'clsx'
import { InsightLegendRow } from './InsightLegendRow'
import { shouldHighlightThisRow, DISPLAY_TYPES_WITHOUT_LEGEND } from './utils'
import { trendsDataLogic } from 'scenes/trends/trendsDataLogic'
import { ChartDisplayType } from '~/types'

export interface InsightLegendProps {
    readOnly?: boolean
    horizontal?: boolean
    inCardView?: boolean
}

export function InsightLegend({ horizontal, inCardView, readOnly = false }: InsightLegendProps): JSX.Element | null {
    // TODO: replace isSingleSeries etc. with data exploration variant
    const { insightProps, highlightedSeries, isSingleSeries, hiddenLegendKeys } = useValues(insightLogic)
    const { toggleVisibility } = useActions(insightLogic)
    const { indexedResults, compare, display, trendsFilter } = useValues(trendsDataLogic(insightProps))

    return DISPLAY_TYPES_WITHOUT_LEGEND.includes(display || ('' as ChartDisplayType)) ? (
        <div
            className={clsx('InsightLegendMenu', 'flex overflow-auto border rounded', {
                'InsightLegendMenu--horizontal': horizontal,
                'InsightLegendMenu--readonly': readOnly,
                'InsightLegendMenu--in-card-view': inCardView,
            })}
        >
            <div className="grid grid-cols-1">
                {indexedResults &&
                    indexedResults.map((item, index) => (
                        <InsightLegendRow
                            key={index}
                            hiddenLegendKeys={hiddenLegendKeys}
                            item={item}
                            rowIndex={index}
                            hasMultipleSeries={!isSingleSeries}
                            highlighted={shouldHighlightThisRow(hiddenLegendKeys, index, highlightedSeries)}
                            toggleVisibility={toggleVisibility}
                            compare={compare}
                            display={display}
                            trendsFilter={trendsFilter}
                        />
                    ))}
            </div>
        </div>
    ) : null
}
