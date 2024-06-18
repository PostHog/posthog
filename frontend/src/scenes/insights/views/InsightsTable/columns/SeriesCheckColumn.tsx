import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { IndexedTrendResult } from 'scenes/trends/types'

type SeriesCheckColumnTitleProps = {
    indexedResults: IndexedTrendResult[]
    canCheckUncheckSeries: boolean
    hiddenLegendIndexes: number[]
    toggleHiddenLegendIndex: (index: number) => void
}

export function SeriesCheckColumnTitle({
    indexedResults,
    canCheckUncheckSeries,
    hiddenLegendIndexes,
    toggleHiddenLegendIndex,
}: SeriesCheckColumnTitleProps): JSX.Element {
    const isAnySeriesChecked = indexedResults.some((series) => !hiddenLegendIndexes.includes(series.id))
    const areAllSeriesChecked = indexedResults.every((series) => !hiddenLegendIndexes.includes(series.id))

    return (
        <LemonCheckbox
            checked={areAllSeriesChecked || (isAnySeriesChecked ? 'indeterminate' : false)}
            onChange={(checked) =>
                indexedResults.forEach((i) => {
                    if (checked && hiddenLegendKeys[i.id]) {
                        toggleVisibility(i.id)
                    } else if (!checked && !hiddenLegendKeys[i.id]) {
                        toggleVisibility(i.id)
                    }
                })
            }
            disabled={!canCheckUncheckSeries}
        />
    )
}

type SeriesCheckColumnItemProps = {
    item: IndexedTrendResult
    canCheckUncheckSeries: boolean
    hiddenLegendIndexes: number[]
    toggleHiddenLegendIndex: (index: number) => void
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
            onChange={() => toggleHiddenLegendIndex(item.id)}
            disabled={!canCheckUncheckSeries}
            label={label}
        />
    )
}
