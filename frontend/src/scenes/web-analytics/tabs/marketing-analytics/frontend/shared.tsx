import { IconGraph, IconLineGraph } from '@posthog/icons'
import { LemonSegmentedButtonOption } from '@posthog/lemon-ui'
import { IconAreaChart } from 'lib/lemon-ui/icons'
import { humanFriendlyNumber } from 'lib/utils'
import { ChartDisplayType } from '~/types'
import { Tooltip } from 'lib/lemon-ui/Tooltip/Tooltip'

// Simple mapping for the display mode options and their icons
export const DISPLAY_MODE_OPTIONS: LemonSegmentedButtonOption<ChartDisplayType>[] = [
    { value: ChartDisplayType.ActionsLineGraph, icon: <IconLineGraph /> },
    { value: ChartDisplayType.ActionsAreaGraph, icon: <IconAreaChart /> },
    { value: ChartDisplayType.ActionsBar, icon: <IconGraph /> },
]

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

    if (typeof current !== 'number' && current === previous) {
        return <span>{current}</span>
    }

    const formatValue = (num: number | null): string => {
        if (num === null || num === undefined) {
            return '-'
        }
        return humanFriendlyNumber(num)
    }

    const calculatePercentageChange = (current: number, previous: number): string => {
        if (previous === 0) {
            return current > 0 ? '+∞%' : current < 0 ? '-∞%' : '0%'
        }

        const change = ((current - previous) / previous) * 100
        const sign = change >= 0 ? '+' : ''
        return `${sign}${change.toFixed(1)}%`
    }

    const getTooltipContent = (current: number | null, previous: number | null): React.ReactNode => {
        let currentValue: string
        if (current === null || current === undefined) {
            currentValue = 'No data'
        } else {
            currentValue = formatValue(current)
        }
        let previousValue: string
        if (previous === null || previous === undefined) {
            previousValue = 'No data'
        } else {
            previousValue = formatValue(previous)
        }
        let percentageChange: string
        if (current === null || previous === null) {
            percentageChange = 'No data'
        } else {
            percentageChange = calculatePercentageChange(current, previous)
        }
        return (
            <div>
                <div>Current period: {currentValue}</div>
                <div>Previous period: {previousValue}</div>
                <div>Change: {percentageChange}</div>
            </div>
        )
    }

    const currentFormatted = formatValue(current)
    const previousFormatted = formatValue(previous)
    const tooltipContent = getTooltipContent(current, previous)

    return (
        <Tooltip title={tooltipContent} delayMs={300}>
            <div className="flex flex-wrap gap-2">
                <div className="w-full">{currentFormatted}</div>
                <div className="w-full text-muted">
                    {previous !== null && previous !== undefined ? previousFormatted : '-'}
                </div>
            </div>
        </Tooltip>
    )
}
