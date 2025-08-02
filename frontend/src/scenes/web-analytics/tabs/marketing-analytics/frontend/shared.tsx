import { IconGraph, IconLineGraph } from '@posthog/icons'
import { LemonSegmentedButtonOption } from '@posthog/lemon-ui'
import { IconAreaChart, IconArrowDown, IconArrowUp } from 'lib/lemon-ui/icons'
import { humanFriendlyLargeNumber, humanFriendlyNumber } from 'lib/utils'
import { ChartDisplayType } from '~/types'
import { Tooltip } from 'lib/lemon-ui/Tooltip/Tooltip'

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

const calculatePercentageChange = (current: number, previous: number): { sign: boolean; percentage: string } => {
    if (previous === 0) {
        if (current > 0) {
            return { sign: true, percentage: '+∞%' }
        }
        if (current < 0) {
            return { sign: false, percentage: '-∞%' }
        }
        return { sign: true, percentage: '0%' }
    }

    const change = ((current - previous) / previous) * 100
    const sign = change >= 0
    const prefix = sign ? '+' : ''
    return { sign, percentage: `${prefix}${change.toFixed(1)}%` }
}

const getChangeDirectionIcon = (current: number | null, previous: number | null): JSX.Element | null => {
    if (current === null || current === undefined || previous === null || previous === undefined) {
        return null
    }

    if (current === previous) {
        return null
    }

    return current > previous ? <IconArrowUp /> : <IconArrowDown />
}

const createTooltipContent = (current: number | null, previous: number | null): React.ReactNode => {
    const currentValue = formatValue(current, 'full')
    const previousValue = formatValue(previous, 'full')

    let changeInfo: React.ReactNode
    if (current === null || previous === null) {
        changeInfo = <div>Change: No data</div>
    } else {
        const { sign, percentage } = calculatePercentageChange(current, previous)
        const icon = sign ? <IconArrowUp /> : <IconArrowDown />
        changeInfo = (
            <div>
                Change: {icon}
                {percentage}
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

export const renderMarketingAnalyticsCell = (value: any): JSX.Element | null => {
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
    if (typeof current !== 'number' && current === previous && current !== null) {
        return <span>{formatValue(current, 'full')}</span>
    }

    const currentFormatted = formatValue(current, 'short')
    const previousFormatted = formatValue(previous, 'short')
    const changeIcon = getChangeDirectionIcon(current, previous)
    const tooltipContent = createTooltipContent(current, previous)

    return (
        <Tooltip title={tooltipContent} delayMs={300}>
            <div className="flex flex-wrap gap-2 hover:bg-accent-highlight-secondary min-w-0">
                <div className="min-w-0 overflow-hidden text-ellipsis whitespace-nowrap">
                    {currentFormatted} {changeIcon}
                </div>
                <div className="min-w-0 overflow-hidden text-ellipsis whitespace-nowrap">{previousFormatted}</div>
            </div>
        </Tooltip>
    )
}
