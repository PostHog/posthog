import './InsightLegend.scss'
import { useActions, useValues } from 'kea'
import { insightLogic } from 'scenes/insights/insightLogic'
import { trendsLogic } from 'scenes/trends/trendsLogic'
import { ChartDisplayType, FilterType, InsightType } from '~/types'
import clsx from 'clsx'
import { isFilterWithDisplay } from 'scenes/insights/sharedUtils'
import { InsightLegendRow } from './InsightLegendRow'

export interface InsightLegendProps {
    readOnly?: boolean
    horizontal?: boolean
    inCardView?: boolean
}

const trendTypeCanShowLegendDenyList = [
    ChartDisplayType.WorldMap,
    ChartDisplayType.ActionsTable,
    ChartDisplayType.BoldNumber,
    ChartDisplayType.ActionsBarValue,
]

const insightViewCanShowLegendAllowList = [InsightType.TRENDS, InsightType.STICKINESS]

export const shouldShowLegend = (filters: Partial<FilterType>): boolean =>
    insightViewCanShowLegendAllowList.includes(filters.insight || InsightType.TRENDS) &&
    isFilterWithDisplay(filters) &&
    !!filters.display &&
    !trendTypeCanShowLegendDenyList.includes(filters.display)

function shouldHighlightThisRow(
    hiddenLegendKeys: Record<string, boolean | undefined>,
    rowIndex: number,
    highlightedSeries: number | null
): boolean {
    const numberOfSeriesToSkip = Object.entries(hiddenLegendKeys).filter(
        ([key, isHidden]) => isHidden && Number(key) < rowIndex
    ).length
    const isSkipped = hiddenLegendKeys[rowIndex]
    return highlightedSeries !== null && !isSkipped && highlightedSeries + numberOfSeriesToSkip === rowIndex
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
