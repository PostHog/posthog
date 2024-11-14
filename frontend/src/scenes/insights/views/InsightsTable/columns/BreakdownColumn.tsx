import { IconGear } from '@posthog/icons'
import { LemonButton, Link, Popover } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { SeriesGlyph } from 'lib/components/SeriesGlyph'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { hexToRGBA, isURL, lightenDarkenColor, RGBToRGBA } from 'lib/utils'
import stringWithWBR from 'lib/utils/stringWithWBR'
import { useState } from 'react'
import { dataThemeLogic } from 'scenes/dataThemeLogic'
import { formatBreakdownType, getTrendLegendColorToken, getTrendLegendEntryKey } from 'scenes/insights/utils'
import { IndexedTrendResult } from 'scenes/trends/types'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import {
    BreakdownFilter,
    ColorAssignmentBy,
    LegendEntryConfig,
    LegendEntryConfigByKey,
    LegendEntryConfigByPosition,
} from '~/queries/schema'

interface BreakdownColumnTitleProps {
    breakdownFilter: BreakdownFilter
}

export function BreakdownColumnTitle({ breakdownFilter }: BreakdownColumnTitleProps): JSX.Element {
    return <PropertyKeyInfo disableIcon disablePopover value={formatBreakdownType(breakdownFilter)} />
}

interface MultipleBreakdownColumnTitleProps {
    children?: string | null
}

export function MultipleBreakdownColumnTitle({ children }: MultipleBreakdownColumnTitleProps): JSX.Element {
    return <PropertyKeyInfo disableIcon disablePopover value={children || 'Breakdown Value'} />
}

type BreakdownColumnItemProps = {
    item: IndexedTrendResult
    canCheckUncheckSeries: boolean
    isMainInsightView: boolean
    toggleHiddenLegendIndex: (index: number) => void
    formatItemBreakdownLabel: (item: IndexedTrendResult) => string
    colorAssignmentBy: ColorAssignmentBy | null | undefined
    legendEntries:
        | Record<string, LegendEntryConfigByKey>
        | Record<number, LegendEntryConfigByPosition>
        | null
        | undefined
    updateLegendEntry: (key: number | string, config: LegendEntryConfig) => void
}

export function BreakdownColumnItem({
    item,
    canCheckUncheckSeries,
    isMainInsightView,
    toggleHiddenLegendIndex,
    formatItemBreakdownLabel,
    colorAssignmentBy,
    legendEntries,
    updateLegendEntry,
}: BreakdownColumnItemProps): JSX.Element {
    const [isSettingsOpen, setSettingsOpen] = useState(false)
    const { getTheme } = useValues(dataThemeLogic)
    const { isDarkModeOn } = useValues(themeLogic)

    const breakdownLabel = formatItemBreakdownLabel(item)
    const formattedLabel = stringWithWBR(breakdownLabel, 20)
    const multiEntityAndToggleable = !isMainInsightView && canCheckUncheckSeries

    const theme = getTheme('posthog')
    const colorToken = getTrendLegendColorToken(colorAssignmentBy, legendEntries, theme, item)
    const legendEntryKey = getTrendLegendEntryKey(colorAssignmentBy, item)

    return (
        <div
            className={multiEntityAndToggleable ? 'flex cursor-pointer' : 'flex'}
            onClick={multiEntityAndToggleable ? () => toggleHiddenLegendIndex(item.id) : undefined}
        >
            {breakdownLabel && (
                <>
                    {isURL(breakdownLabel) ? (
                        <Link to={breakdownLabel} target="_blank" className="value-link" targetBlankIcon>
                            {formattedLabel}
                        </Link>
                    ) : (
                        <div title={breakdownLabel}>{formattedLabel}</div>
                    )}

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
                </>
            )}
        </div>
    )
}
