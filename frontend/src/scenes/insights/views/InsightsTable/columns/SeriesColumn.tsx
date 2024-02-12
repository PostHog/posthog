import clsx from 'clsx'
import { getSeriesColor } from 'lib/colors'
import { InsightLabel } from 'lib/components/InsightLabel'
import { IconEdit } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { capitalizeFirstLetter } from 'lib/utils'
import { IndexedTrendResult } from 'scenes/trends/types'

import { TrendResult } from '~/types'

type SeriesColumnItemProps = {
    item: IndexedTrendResult
    indexedResults: IndexedTrendResult[]
    canEditSeriesNameInline: boolean
    compare?: boolean | null
    handleEditClick: (item: IndexedTrendResult) => void
    hasMultipleSeries?: boolean
}

export function SeriesColumnItem({
    item,
    indexedResults,
    canEditSeriesNameInline,
    compare,
    handleEditClick,
    hasMultipleSeries,
}: SeriesColumnItemProps): JSX.Element {
    const showCountedByTag = !!indexedResults.find(({ action }) => action?.math && action.math !== 'total')

    return (
        <div className="series-name-wrapper-col space-x-1">
            <InsightLabel
                seriesColor={getSeriesColor(item.seriesIndex, compare || false)}
                action={item.action}
                fallbackName={item.breakdown_value === '' ? 'None' : item.label}
                hasMultipleSeries={hasMultipleSeries}
                showEventName
                showCountedByTag={showCountedByTag}
                breakdownValue={item.breakdown_value === '' ? 'None' : item.breakdown_value?.toString()}
                hideBreakdown
                hideIcon
                className={clsx({
                    editable: canEditSeriesNameInline,
                })}
                pillMaxWidth={165}
                compareValue={compare ? formatCompareLabel(item) : undefined}
                onLabelClick={canEditSeriesNameInline ? () => handleEditClick(item) : undefined}
            />
            {canEditSeriesNameInline && (
                <LemonButton
                    onClick={() => handleEditClick(item)}
                    title="Rename graph series"
                    icon={<IconEdit className="edit-icon" />}
                />
            )}
        </div>
    )
}

export const formatCompareLabel = (trendResult: TrendResult): string => {
    // label splitting ensures backwards compatibility for api results that don't contain the new compare_label
    const labels = trendResult.label.split(' - ')
    return capitalizeFirstLetter(trendResult.compare_label ?? labels?.[labels.length - 1] ?? 'current')
}
