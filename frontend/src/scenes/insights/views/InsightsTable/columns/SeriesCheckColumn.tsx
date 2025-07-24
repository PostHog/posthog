import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { IndexedTrendResult } from 'scenes/trends/types'

type SeriesCheckColumnTitleProps = {
    indexedResults: IndexedTrendResult[]
    canCheckUncheckSeries: boolean
    hiddenLegendIndexes: number[]
    updateHiddenLegendIndexes: (hiddenLegendIndexes: number[] | undefined) => void
}

export function SeriesCheckColumnTitle({
    indexedResults,
    canCheckUncheckSeries,
    hiddenLegendIndexes,
    updateHiddenLegendIndexes,
}: SeriesCheckColumnTitleProps): JSX.Element {
    const isAnySeriesChecked = indexedResults.some((series) => !hiddenLegendIndexes.includes(series.id))
    const areAllSeriesChecked = indexedResults.every((series) => !hiddenLegendIndexes.includes(series.id))

    return (
        <LemonCheckbox
            checked={areAllSeriesChecked || (isAnySeriesChecked ? 'indeterminate' : false)}
            onChange={(checked) => {
                if (!checked) {
                    updateHiddenLegendIndexes(indexedResults.map((i) => i.id))
                } else {
                    updateHiddenLegendIndexes([])
                }
            }}
            disabled={!canCheckUncheckSeries}
        />
    )
}

type SeriesCheckColumnItemProps = {
    item: IndexedTrendResult
    canCheckUncheckSeries: boolean
    hiddenLegendIndexes: number[]
    toggleHiddenLegendIndex: (dataset: IndexedTrendResult) => void
    label?: JSX.Element
}

export function SeriesCheckColumnItem({
    item,
    canCheckUncheckSeries,
    hiddenLegendIndexes,
    toggleHiddenLegendIndex,
    label,
}: SeriesCheckColumnItemProps): JSX.Element {
    return (
        <LemonCheckbox
            checked={!hiddenLegendIndexes.includes(item.id)}
            onChange={() => toggleHiddenLegendIndex(item)}
            disabled={!canCheckUncheckSeries}
            label={label}
        />
    )
}
