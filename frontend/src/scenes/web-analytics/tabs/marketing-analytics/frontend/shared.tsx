import { IconGraph, IconLineGraph } from '@posthog/icons'
import { LemonSegmentedButtonOption } from '@posthog/lemon-ui'
import { IconAreaChart } from 'lib/lemon-ui/icons'
import { humanFriendlyNumber } from 'lib/utils'
import { ChartDisplayType } from '~/types'

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
        return <span>{String(value)}</span>
    }

    const [current, previous] = value as [number, number]

    const formatValue = (num: number | null): string => {
        if (num === null || num === undefined) {
            return '-'
        }
        return humanFriendlyNumber(num)
    }

    const currentFormatted = formatValue(current)
    const previousFormatted = formatValue(previous)

    return (
        <div className="flex flex-wrap gap-2">
            <div className="w-full">{currentFormatted}</div>
            <div className="w-full text-muted">
                {previous !== null && previous !== undefined ? previousFormatted : '-'}
            </div>
        </div>
    )
}
