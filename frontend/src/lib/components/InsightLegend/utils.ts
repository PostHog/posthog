import { ChartDisplayType } from '~/types'

export const DISPLAY_TYPES_WITHOUT_LEGEND = [
    ChartDisplayType.WorldMap,
    ChartDisplayType.ActionsTable,
    ChartDisplayType.BoldNumber,
    ChartDisplayType.ActionsBarValue,
]

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
