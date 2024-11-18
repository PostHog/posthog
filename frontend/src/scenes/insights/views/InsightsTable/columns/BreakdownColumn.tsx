import { IconGear } from '@posthog/icons'
import { LemonButton, Link, Popover } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { SeriesGlyph } from 'lib/components/SeriesGlyph'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { hexToRGBA, isURL, lightenDarkenColor, RGBToRGBA } from 'lib/utils'
import stringWithWBR from 'lib/utils/stringWithWBR'
import { useState } from 'react'
import { dataThemeLogic } from 'scenes/dataThemeLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import {
    formatBreakdownType,
    getTrendLegendColorToken,
    getTrendLegendEntryKey,
    getTrendsLegendEntry,
} from 'scenes/insights/utils'
import { IndexedTrendResult } from 'scenes/trends/types'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import {
    BreakdownFilter,
    ColorAssignmentBy,
    LegendEntryConfig,
    LegendEntryConfigByKey,
    LegendEntryConfigByPosition,
} from '~/queries/schema'
import { legendEntryModalLogic } from '../legendEntryModalLogic'

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
    formatItemBreakdownLabel,
    colorAssignmentBy,
    legendEntries,
    updateLegendEntry,
}: BreakdownColumnItemProps): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const [isSettingsOpen, setSettingsOpen] = useState(false)
    const { openModal } = useActions(legendEntryModalLogic(insightProps))
    const { getTheme } = useValues(dataThemeLogic)
    const { isDarkModeOn } = useValues(themeLogic)

    const breakdownLabel = formatItemBreakdownLabel(item)
    const formattedLabel = stringWithWBR(breakdownLabel, 20)

    const theme = getTheme('posthog')
    const colorToken = getTrendLegendColorToken(colorAssignmentBy, legendEntries, theme, item)
    const legendEntryKey = getTrendLegendEntryKey(colorAssignmentBy, item)
    const legendEntry = getTrendsLegendEntry(colorAssignmentBy, item, legendEntries)

    return (
        <div className="flex">
            {breakdownLabel && (
                <>
                    {isURL(breakdownLabel) ? (
                        <Link to={breakdownLabel} target="_blank" className="value-link font-medium" targetBlankIcon>
                            {formattedLabel}
                        </Link>
                    ) : (
                        <div title={breakdownLabel} className="font-medium">
                            {formattedLabel}
                        </div>
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
                        <Link
                            className="align-middle"
                            onClick={(e) => {
                                e.preventDefault()
                                e.stopPropagation()
                                // setSettingsOpen(true)
                                openModal(item)
                            }}
                        >
                            <IconGear fontSize={16} />
                        </Link>
                    </Popover>
                </>
            )}
        </div>
    )
}
