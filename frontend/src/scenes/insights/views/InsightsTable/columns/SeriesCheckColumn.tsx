import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { getSeriesColor } from 'lib/colors'
import { IndexedTrendResult } from 'scenes/trends/types'

type SeriesCheckColumnTitleProps = {
    indexedResults: IndexedTrendResult[]
    canCheckUncheckSeries: boolean
    hiddenLegendKeys: Record<string, boolean | undefined>
    toggleVisibility: (id: number) => void
}

export function SeriesCheckColumnTitle({
    indexedResults,
    canCheckUncheckSeries,
    hiddenLegendKeys,
    toggleVisibility,
}: SeriesCheckColumnTitleProps): JSX.Element {
    const isAnySeriesChecked = indexedResults.some((series) => !hiddenLegendKeys[series.id])
    const areAllSeriesChecked = indexedResults.every((series) => !hiddenLegendKeys[series.id])

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
    hiddenLegendKeys: Record<string, boolean | undefined>
    compare?: boolean
    toggleVisibility: (id: number) => void
}

export function SeriesCheckColumnItem({
    item,
    canCheckUncheckSeries,
    hiddenLegendKeys,
    compare,
    toggleVisibility,
}: SeriesCheckColumnItemProps): JSX.Element {
    return (
        <LemonCheckbox
            color={getSeriesColor(item.seriesIndex, compare)}
            checked={!hiddenLegendKeys[item.id]}
            onChange={() => toggleVisibility(item.id)}
            disabled={!canCheckUncheckSeries}
        />
    )
}
