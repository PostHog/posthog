import './InsightLegend.scss'

import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { insightLogic } from 'scenes/insights/insightLogic'
import { trendsDataLogic } from 'scenes/trends/trendsDataLogic'

import { InsightLegendRow } from './InsightLegendRow'
import { shouldHighlightThisRow } from './utils'

export interface InsightLegendProps {
    readOnly?: boolean
    horizontal?: boolean
    inCardView?: boolean
}

export function InsightLegend({ horizontal, inCardView, readOnly = false }: InsightLegendProps): JSX.Element | null {
    const { insightProps, highlightedSeries, hiddenLegendKeys } = useValues(insightLogic)
    const { toggleVisibility } = useActions(insightLogic)
    const { indexedResults, compare, display, trendsFilter, hasLegend, isSingleSeries } = useValues(
        trendsDataLogic(insightProps)
    )

    return hasLegend ? (
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
