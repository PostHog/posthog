import { ChartDisplayType } from '~/types'

export const DISPLAY_TYPES_WITHOUT_LEGEND = [
    ChartDisplayType.WorldMap,
    ChartDisplayType.ActionsTable,
    ChartDisplayType.BoldNumber,
    ChartDisplayType.ActionsBarValue,
]

export const DISPLAY_TYPES_WITHOUT_DETAILED_RESULTS = [
    ChartDisplayType.ActionsTable, // The table is already loaded as the main component (in `Trends.tsx`)
    ChartDisplayType.ActionsBarValue, // This view displays data in completely different dimensions
]

export function shouldHighlightThisRow(
    currentIndex: number,
    highlightedIndex: number | null,
    hiddenLegendIndexes: number[] | undefined
): boolean {
    const numberOfSeriesToSkip = hiddenLegendIndexes?.filter((index) => index < currentIndex).length || 0
    const isSkipped = hiddenLegendIndexes?.includes[currentIndex]
    return highlightedIndex !== null && !isSkipped && highlightedIndex + numberOfSeriesToSkip === currentIndex
}
