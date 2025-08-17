import { IconGraph, IconLineGraph } from '@posthog/icons'
import { LemonSegmentedButtonOption } from '@posthog/lemon-ui'

import { Tooltip } from 'lib/lemon-ui/Tooltip/Tooltip'
import { IconAreaChart, IconArrowDown, IconArrowUp } from 'lib/lemon-ui/icons'
import { humanFriendlyLargeNumber, humanFriendlyNumber } from 'lib/utils'

import { ChartDisplayType } from '~/types'

// Simple mapping for the display mode options and their icons
export const DISPLAY_MODE_OPTIONS: LemonSegmentedButtonOption<ChartDisplayType>[] = [
    { value: ChartDisplayType.ActionsLineGraph, icon: <IconLineGraph /> },
    { value: ChartDisplayType.ActionsAreaGraph, icon: <IconAreaChart /> },
    { value: ChartDisplayType.ActionsBar, icon: <IconGraph /> },
]

const formatValue = (value: number | null | undefined, mode: 'full' | 'short'): string => {
    if (value === null || value === undefined) {
        return '-'
    }
    switch (mode) {
        case 'full':
            return humanFriendlyNumber(value, 1)
        case 'short':
            return humanFriendlyLargeNumber(value)
    }
    return value.toString()
}

const getChangeDirectionIcon = (current: number | null, previous: number | null): JSX.Element | null => {
    if (current === previous) {
        return null
    }
    return (current ?? 0) > (previous ?? 0) ? <IconArrowUp /> : <IconArrowDown />
}

const createTooltipContent = (
    current: number | null,
    previous: number | null,
    changePerc: number | null
): React.ReactNode => {
    const currentValue = formatValue(current, 'full')
    const previousValue = formatValue(previous, 'full')

    let changeInfo: React.ReactNode
    if (previous === null) {
        changeInfo = <div>Change: No data</div>
    } else if (changePerc === null) {
        changeInfo = <div>Change: {current}</div>
    } else {
        const icon = changePerc > 0 ? <IconArrowUp /> : <IconArrowDown />
        changeInfo = (
            <div>
                Change: {changePerc.toFixed(2)}% {icon}
            </div>
        )
    }

    return (
        <div>
            <div>Current period: {currentValue}</div>
            <div>Previous period: {previousValue}</div>
            {changeInfo}
        </div>
    )
}

export const MarketingAnalyticsCell = ({ value }: any): JSX.Element | null => {
    if (!value) {
        return <span>-</span>
    }

    if (!Array.isArray(value)) {
        if (typeof value === 'number') {
            return <span>{humanFriendlyNumber(value)}</span>
        }
        return <span>{value}</span>
    }

    const [current, previous] = value as [number, number]

    // Handle case where both values are the same non-null value
    if (typeof current == 'string' && current === previous) {
        return <span>{current}</span>
    }

    const currentFormatted = formatValue(current, 'short')
    const changeIcon = getChangeDirectionIcon(current, previous)
    const changePerc = previous === 0 ? null : (((current ?? 0) - previous) / previous) * 100
    const changePercFormatted = changePerc ? `${changePerc.toFixed(2)}%` : null
    const tooltipContent = createTooltipContent(current, previous, changePerc)

    return (
        <Tooltip title={tooltipContent} delayMs={300}>
            <div className="flex flex-wrap gap-2 hover:bg-accent-highlight-secondary min-w-0">
                <div className="min-w-0 overflow-hidden text-ellipsis whitespace-nowrap">
                    {currentFormatted} {changeIcon}
                </div>
                <div className="w-full text-muted">{changePercFormatted}</div>
            </div>
        </Tooltip>
    )
}
