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
    /** Double-click isolate handler. The double-click's constituent clicks still toggle the
     *  checkbox twice; the two toggles cancel out, so the handler runs against the hidden state
     *  the gesture started from. */
    onDoubleClick?: (dataset: IndexedTrendResult) => void
}

export function SeriesCheckColumnItem({
    item,
    canCheckUncheckSeries,
    isHidden,
    toggleResultHidden,
    label,
    disabledReason,
    onDoubleClick,
}: SeriesCheckColumnItemProps): JSX.Element {
    const checkbox = (
        <LemonCheckbox
            checked={!isHidden}
            onChange={() => toggleResultHidden(item)}
            disabled={!canCheckUncheckSeries}
            disabledReason={disabledReason}
            label={label}
        />
    )

    if (!onDoubleClick) {
        return checkbox
    }

    // LemonCheckbox exposes no double-click prop, so the wrapper carries the gesture. select-none
    // stops the double-click from selecting the row's label text.
    return (
        <div className="select-none" onDoubleClick={() => onDoubleClick(item)}>
            {checkbox}
        </div>
    )
}
