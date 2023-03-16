import './InsightLegend.scss'
import { useActions, useValues } from 'kea'
import { insightLogic } from 'scenes/insights/insightLogic'
import { trendsLogic } from 'scenes/trends/trendsLogic'
import clsx from 'clsx'
import { InsightLegendRow } from './InsightLegendRow'
import { shouldShowLegend, shouldHighlightThisRow } from './utils'

export interface InsightLegendProps {
    readOnly?: boolean
    horizontal?: boolean
    inCardView?: boolean
}

export function InsightLegend({ horizontal, inCardView, readOnly = false }: InsightLegendProps): JSX.Element | null {
    const { insightProps, filters, highlightedSeries } = useValues(insightLogic)
    const logic = trendsLogic(insightProps)
    const { indexedResults, hiddenLegendKeys } = useValues(logic)
    const { toggleVisibility } = useActions(logic)

    return shouldShowLegend(filters) ? (
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
                            hasMultipleSeries={indexedResults.length > 1}
                            highlighted={shouldHighlightThisRow(hiddenLegendKeys, index, highlightedSeries)}
                            toggleVisibility={toggleVisibility}
                            filters={filters}
                        />
                    ))}
            </div>
        </div>
    ) : null
}
