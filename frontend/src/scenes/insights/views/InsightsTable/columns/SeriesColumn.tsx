import { IconGear, IconPencil } from '@posthog/icons'
import { Popover } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useValues } from 'kea'
import { getTrendLikeSeriesColor } from 'lib/colors'
import { InsightLabel } from 'lib/components/InsightLabel'
import { SeriesGlyph } from 'lib/components/SeriesGlyph'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { capitalizeFirstLetter, hexToRGBA, lightenDarkenColor, RGBToRGBA } from 'lib/utils'
import { useState } from 'react'
import { dataThemeLogic } from 'scenes/dataThemeLogic'
import { getTrendLegendColorToken, getTrendLegendEntryKey } from 'scenes/insights/utils'
import { IndexedTrendResult } from 'scenes/trends/types'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import {
    ColorAssignmentBy,
    LegendEntryConfig,
    LegendEntryConfigByKey,
    LegendEntryConfigByPosition,
} from '~/queries/schema'
import { TrendResult } from '~/types'

type SeriesColumnItemProps = {
    item: IndexedTrendResult
    indexedResults: IndexedTrendResult[]
    canEditSeriesNameInline: boolean
    handleEditClick: (item: IndexedTrendResult) => void
    hasMultipleSeries: boolean
    hasBreakdown: boolean
    colorAssignmentBy: ColorAssignmentBy | null | undefined
    legendEntries:
        | Record<string, LegendEntryConfigByKey>
        | Record<number, LegendEntryConfigByPosition>
        | null
        | undefined
    updateLegendEntry: (key: number | string, config: LegendEntryConfig) => void
}

export function SeriesColumnItem({
    item,
    indexedResults,
    canEditSeriesNameInline,
    handleEditClick,
    hasMultipleSeries,
    hasBreakdown,
    colorAssignmentBy,
    legendEntries,
    updateLegendEntry,
}: SeriesColumnItemProps): JSX.Element {
    const [isSettingsOpen, setSettingsOpen] = useState(false)
    const { getTheme } = useValues(dataThemeLogic)
    const { isDarkModeOn } = useValues(themeLogic)

    const showCountedByTag = !!indexedResults.find(({ action }) => action?.math && action.math !== 'total')

    const isPrevious = !!item.compare && item.compare_label === 'previous'

    const theme = getTheme('posthog')
    const colorToken = getTrendLegendColorToken(colorAssignmentBy, legendEntries, theme, item)
    const legendEntryKey = getTrendLegendEntryKey(colorAssignmentBy, item)

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
                    noPadding
                    size="small"
                    onClick={() => handleEditClick(item)}
                    title="Rename graph series"
                    icon={<IconPencil className="edit-icon" />}
                />
            )}
            {!hasBreakdown && (
                <Popover
                    overlay={
                        <div className="m-2 min-w-50">
                            <div className="flex gap-3">
                                <LemonField.Pure label="Color">
                                    <div className="flex">
                                        {Object.entries(theme).map(([key, color]) => (
                                            <LemonButton
                                                key={key}
                                                type={key === colorToken ? 'secondary' : 'tertiary'}
                                                onClick={(e) => {
                                                    e.preventDefault()
                                                    e.stopPropagation()
                                                    updateLegendEntry(legendEntryKey, { color: key })
                                                }}
                                            >
                                                <SeriesGlyph
                                                    style={{
                                                        borderColor: color,
                                                        color: color,
                                                        backgroundColor: isDarkModeOn
                                                            ? RGBToRGBA(lightenDarkenColor(color, -20), 0.3)
                                                            : hexToRGBA(color, 0.5),
                                                    }}
                                                />
                                            </LemonButton>
                                        ))}
                                    </div>
                                </LemonField.Pure>

                                <LemonButton>Reset</LemonButton>
                            </div>
                        </div>
                    }
                    visible={isSettingsOpen}
                    placement="right"
                    onClickOutside={() => {
                        setSettingsOpen(false)
                    }}
                >
                    <LemonButton
                        icon={<IconGear />}
                        noPadding
                        className="ml-1"
                        size="small"
                        onClick={(e) => {
                            e.preventDefault()
                            e.stopPropagation()
                            setSettingsOpen(true)
                        }}
                    />
                </Popover>
            )}
        </div>
    )
}

export const formatCompareLabel = (trendResult: TrendResult): string => {
    // label splitting ensures backwards compatibility for api results that don't contain the new compare_label
    const labels = trendResult.label?.split(' - ')
    return capitalizeFirstLetter(trendResult.compare_label ?? labels?.[labels.length - 1] ?? 'current')
}
