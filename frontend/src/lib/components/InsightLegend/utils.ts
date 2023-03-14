import { ChartDisplayType, FilterType } from '~/types'
import { isFilterWithDisplay } from 'scenes/insights/sharedUtils'

export const displayTypesWithoutLegend = [
    ChartDisplayType.WorldMap,
    ChartDisplayType.ActionsTable,
    ChartDisplayType.BoldNumber,
    ChartDisplayType.ActionsBarValue,
]

export const shouldShowLegend = (filters: Partial<FilterType>): boolean =>
    isFilterWithDisplay(filters) && !!filters.display && !displayTypesWithoutLegend.includes(filters.display)

export function shouldHighlightThisRow(
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
