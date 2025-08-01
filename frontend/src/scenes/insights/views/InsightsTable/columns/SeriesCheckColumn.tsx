import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { IndexedTrendResult } from 'scenes/trends/types'

type SeriesCheckColumnTitleProps = {
    indexedResults: IndexedTrendResult[]
    canCheckUncheckSeries: boolean
    getTrendsHidden: (dataset: IndexedTrendResult) => boolean
    toggleAllHiddenLegendIndexes: (datasets: IndexedTrendResult[], hidden: boolean) => void
}

export function SeriesCheckColumnTitle({
    indexedResults,
    canCheckUncheckSeries,
    getTrendsHidden,
    toggleAllHiddenLegendIndexes,
}: SeriesCheckColumnTitleProps): JSX.Element {
    // return null
    const isAnySeriesChecked = indexedResults.some((dataset) => !getTrendsHidden(dataset))
    const areAllSeriesChecked = indexedResults.every((dataset) => !getTrendsHidden(dataset))

    return (
        <LemonCheckbox
            checked={areAllSeriesChecked || (isAnySeriesChecked ? 'indeterminate' : false)}
            onChange={(checked) => {
                if (!checked) {
                    toggleAllHiddenLegendIndexes(indexedResults, true)
                } else {
                    toggleAllHiddenLegendIndexes(indexedResults, false)
                }
            }}
            disabled={!canCheckUncheckSeries}
        />
    )
}

type SeriesCheckColumnItemProps = {
    item: IndexedTrendResult
    canCheckUncheckSeries: boolean
    isHidden: boolean
    toggleHiddenLegendIndex: (dataset: IndexedTrendResult) => void
    label?: JSX.Element
}

export function SeriesCheckColumnItem({
    item,
    canCheckUncheckSeries,
    isHidden,
    toggleHiddenLegendIndex,
    label,
}: SeriesCheckColumnItemProps): JSX.Element {
    return (
        <LemonCheckbox
            checked={!isHidden}
            onChange={() => toggleHiddenLegendIndex(item)}
            disabled={!canCheckUncheckSeries}
            label={label}
        />
    )
}
