import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { IndexedTrendResult } from 'scenes/trends/types'

type SeriesCheckColumnTitleProps = {
    indexedResults: IndexedTrendResult[]
    canCheckUncheckSeries: boolean
    getTrendsHidden: (dataset: IndexedTrendResult) => boolean
    toggleAllResultsHidden: (datasets: IndexedTrendResult[], hidden: boolean) => void
    disabledReason?: string | null
}

export function SeriesCheckColumnTitle({
    indexedResults,
    canCheckUncheckSeries,
    getTrendsHidden,
    toggleAllResultsHidden,
    disabledReason,
}: SeriesCheckColumnTitleProps): JSX.Element {
    const isAnySeriesChecked = indexedResults.some((dataset) => !getTrendsHidden(dataset))
    const areAllSeriesChecked = indexedResults.every((dataset) => !getTrendsHidden(dataset))

    return (
        <LemonCheckbox
            checked={areAllSeriesChecked || (isAnySeriesChecked ? 'indeterminate' : false)}
            onChange={(checked) => {
                if (!checked) {
                    toggleAllResultsHidden(indexedResults, true)
                } else {
                    toggleAllResultsHidden(indexedResults, false)
                }
            }}
            disabled={!canCheckUncheckSeries}
            disabledReason={disabledReason}
        />
    )
}

type SeriesCheckColumnItemProps = {
    item: IndexedTrendResult
    canCheckUncheckSeries: boolean
    isHidden: boolean
    toggleResultHidden: (dataset: IndexedTrendResult) => void
    label?: JSX.Element
    disabledReason?: string | null
}

export function SeriesCheckColumnItem({
    item,
    canCheckUncheckSeries,
    isHidden,
    toggleResultHidden,
    label,
    disabledReason,
}: SeriesCheckColumnItemProps): JSX.Element {
    return (
        <LemonCheckbox
            checked={!isHidden}
            onChange={() => toggleResultHidden(item)}
            disabled={!canCheckUncheckSeries}
            disabledReason={disabledReason}
            label={label}
        />
    )
}
