import { IconPencil } from '@posthog/icons'
import clsx from 'clsx'
import { getTrendLikeSeriesColor } from 'lib/colors'
import { InsightLabel } from 'lib/components/InsightLabel'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { capitalizeFirstLetter } from 'lib/utils'
import { IndexedTrendResult } from 'scenes/trends/types'

import { TrendResult } from '~/types'

type SeriesColumnItemProps = {
    item: IndexedTrendResult
    indexedResults: IndexedTrendResult[]
    canEditSeriesNameInline: boolean
    handleEditClick: (item: IndexedTrendResult) => void
    hasMultipleSeries?: boolean
}

export function SeriesColumnItem({
    item,
    indexedResults,
    canEditSeriesNameInline,
    handleEditClick,
    hasMultipleSeries,
}: SeriesColumnItemProps): JSX.Element {
    const showCountedByTag = !!indexedResults.find(({ action }) => action?.math && action.math !== 'total')

    const isPrevious = !!item.compare && item.compare_label === 'previous'

    return (
        <div className="series-name-wrapper-col space-x-1">
            <InsightLabel
                seriesColor={getTrendLikeSeriesColor(item.colorIndex, isPrevious)}
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
                compareValue={item.compare ? formatCompareLabel(item) : undefined}
                onLabelClick={canEditSeriesNameInline ? () => handleEditClick(item) : undefined}
            />
            {canEditSeriesNameInline && (
                <LemonButton
                    onClick={() => handleEditClick(item)}
                    title="Rename graph series"
                    icon={<IconPencil className="edit-icon" />}
                />
            )}
        </div>
    )
}

export const formatCompareLabel = (trendResult: TrendResult): string => {
    // label splitting ensures backwards compatibility for api results that don't contain the new compare_label
    const labels = trendResult.label?.split(' - ')
    return capitalizeFirstLetter(trendResult.compare_label ?? labels?.[labels.length - 1] ?? 'current')
}
