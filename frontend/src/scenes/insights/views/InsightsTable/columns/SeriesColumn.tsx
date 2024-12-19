import { IconPencil } from '@posthog/icons'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { InsightLabel } from 'lib/components/InsightLabel'
import { capitalizeFirstLetter } from 'lib/utils'
import { useState } from 'react'
import { insightLogic } from 'scenes/insights/insightLogic'
import { IndexedTrendResult } from 'scenes/trends/types'

import { TrendResult } from '~/types'

import { resultCustomizationsModalLogic } from '../../../../../queries/nodes/InsightViz/resultCustomizationsModalLogic'

type CustomizationIconProps = {
    isVisible: boolean
}

export const CustomizationIcon = ({ isVisible }: CustomizationIconProps): JSX.Element | null => {
    const { insightProps } = useValues(insightLogic)
    const { hasInsightColors } = useValues(resultCustomizationsModalLogic(insightProps))

    if (!hasInsightColors) {
        return null
    }

    // we always render a spacer so that hovering doesn't result in layout shifts
    return <div className="w-4 h-4 flex">{isVisible && <IconPencil fontSize={14} />}</div>
}

type SeriesColumnItemProps = {
    item: IndexedTrendResult
    indexedResults: IndexedTrendResult[]
    canEditSeriesNameInline: boolean
    handleEditClick: (item: IndexedTrendResult) => void
    hasMultipleSeries: boolean
    hasBreakdown: boolean
}

export function SeriesColumnItem({
    item,
    indexedResults,
    canEditSeriesNameInline,
    handleEditClick,
    hasMultipleSeries,
    hasBreakdown,
}: SeriesColumnItemProps): JSX.Element {
    const [isHovering, setIsHovering] = useState(false)
    const { insightProps } = useValues(insightLogic)
    const { hasInsightColors } = useValues(resultCustomizationsModalLogic(insightProps))
    const { openModal } = useActions(resultCustomizationsModalLogic(insightProps))

    const showCountedByTag = !!indexedResults.find(({ action }) => action?.math && action.math !== 'total')
    const showCustomizationIcon = hasInsightColors && !hasBreakdown

    return (
        <div
            className="series-name-wrapper-col space-x-1"
            onClick={
                showCustomizationIcon
                    ? (e) => {
                          e.preventDefault()
                          e.stopPropagation()

                          openModal(item)
                      }
                    : undefined
            }
            onMouseEnter={() => setIsHovering(true)}
            onMouseLeave={() => setIsHovering(false)}
        >
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
                onLabelClick={
                    canEditSeriesNameInline && !showCustomizationIcon ? () => handleEditClick(item) : undefined
                }
            />
            {/* rendering and visibility are separated, so that we can render a placeholder */}
            {showCustomizationIcon && <CustomizationIcon isVisible={isHovering} />}
        </div>
    )
}

export const formatCompareLabel = (trendResult: TrendResult): string => {
    // label splitting ensures backwards compatibility for api results that don't contain the new compare_label
    const labels = trendResult.label?.split(' - ')
    return capitalizeFirstLetter(trendResult.compare_label ?? labels?.[labels.length - 1] ?? 'current')
}
