import clsx from 'clsx'

import { Tooltip } from '@posthog/lemon-ui'

import { InsightLabel } from 'lib/components/InsightLabel'
import { capitalizeFirstLetter } from 'lib/utils'
import { IndexedTrendResult } from 'scenes/trends/types'

import { TrendResult } from '~/types'

type SeriesColumnItemProps = {
    item: IndexedTrendResult
    indexedResults: IndexedTrendResult[]
    canEditSeriesNameInline: boolean
    seriesNameTooltip?: string
    handleEditClick: (item: IndexedTrendResult) => void
    hasMultipleSeries: boolean
    hasBreakdown: boolean
}

export function SeriesColumnItem({
    item,
    indexedResults,
    canEditSeriesNameInline,
    seriesNameTooltip,
    handleEditClick,
    hasMultipleSeries,
    hasBreakdown,
}: SeriesColumnItemProps): JSX.Element {
    const showCountedByTag = !!indexedResults.find(({ action }) => action?.math && action.math !== 'total')

    return (
        <Tooltip title={seriesNameTooltip}>
            <div className="series-name-wrapper-col deprecated-space-x-1">
                <InsightLabel
                    action={item.action}
                    fallbackName={item.breakdown_value === '' ? 'None' : item.label}
                    hasMultipleSeries={hasMultipleSeries}
                    showEventName
                    showCountedByTag={showCountedByTag}
                    hideBreakdown
                    hideIcon
                    className={clsx({
                        'font-medium': !hasBreakdown,
                    })}
                    pillMaxWidth={165}
                    compareValue={item.compare ? formatCompareLabel(item) : undefined}
                    onLabelClick={canEditSeriesNameInline ? () => handleEditClick(item) : undefined}
                />
            </div>
        </Tooltip>
    )
}

export const formatCompareLabel = (trendResult: TrendResult): string => {
    // label splitting ensures backwards compatibility for api results that don't contain the new compare_label
    const labels = trendResult.label?.split(' - ')
    return capitalizeFirstLetter(trendResult.compare_label ?? labels?.[labels.length - 1] ?? 'current')
}
