import { useValues } from 'kea'

import { IconGraph, IconLineGraph, IconTrending } from '@posthog/icons'
import { LemonSegmentedButtonOption } from '@posthog/lemon-ui'

import { getColorVar } from 'lib/colors'
import { Tooltip } from 'lib/lemon-ui/Tooltip/Tooltip'
import { IconAreaChart, IconTrendingDown, IconTrendingFlat } from 'lib/lemon-ui/icons'
import { humanFriendlyDuration, humanFriendlyLargeNumber, humanFriendlyNumber, percentage } from 'lib/utils'
import { isNotNil } from 'lib/utils'
import { DEFAULT_CURRENCY, getCurrencySymbol } from 'lib/utils/geography/currency'
import { teamLogic } from 'scenes/teamLogic'

import { InfinityValue, MarketingAnalyticsItem, WebAnalyticsItemKind } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

// Simple mapping for the display mode options and their icons
export const DISPLAY_MODE_OPTIONS: LemonSegmentedButtonOption<ChartDisplayType>[] = [
    { value: ChartDisplayType.ActionsLineGraph, icon: <IconLineGraph /> },
    { value: ChartDisplayType.ActionsAreaGraph, icon: <IconAreaChart /> },
    { value: ChartDisplayType.ActionsBar, icon: <IconGraph /> },
]

const formatMarketingItem = (
    value: number | string | undefined,
    kind: WebAnalyticsItemKind,
    options?: { precise?: boolean; currency?: string; hideCurrency?: boolean }
): string => {
    if (value == null) {
        return '-'
    } else if (typeof value === 'string') {
        return value // Return strings as-is (for Campaign, Source)
    } else if (kind === 'percentage') {
        return percentage(value / 100, options?.precise ? 3 : 2) // Convert back from percentage to decimal for formatting
    } else if (kind === 'duration_s') {
        return humanFriendlyDuration(value, { secondsPrecision: 3 })
    } else if (kind === 'currency') {
        const formattedValue = options?.precise ? humanFriendlyNumber(value) : humanFriendlyLargeNumber(value)

        if (options?.hideCurrency) {
            return formattedValue // Return just the number without currency symbol
        }

        const { symbol, isPrefix } = getCurrencySymbol(options?.currency ?? DEFAULT_CURRENCY)
        return `${isPrefix ? symbol : ''}${formattedValue}${isPrefix ? '' : ' ' + symbol}`
    }
    return options?.precise ? humanFriendlyNumber(value) : humanFriendlyLargeNumber(value)
}

// Helper to format percentage change including infinity cases
const formatChangePercentage = (changeFromPreviousPct: number | null | undefined): string | null => {
    if (!isNotNil(changeFromPreviousPct)) {
        return null
    }

    if (changeFromPreviousPct === InfinityValue.INFINITY_VALUE) {
        return '∞%'
    }
    if (changeFromPreviousPct === InfinityValue.NEGATIVE_INFINITY_VALUE) {
        return '-∞%'
    }

    return percentage(changeFromPreviousPct / 100, 2)
}

// Helper for special change cases (infinity, no change)
const getSpecialChangeTooltip = (item: MarketingAnalyticsItem, baseCurrency: string): string | null => {
    if (item.changeFromPreviousPct === 0) {
        return `${item.key}: ${formatMarketingItem(item.value, item.kind, { precise: true, currency: baseCurrency })} (no change from previous period)`
    }
    if (item.changeFromPreviousPct === InfinityValue.INFINITY_VALUE) {
        return `${item.key}: new activity at ${formatMarketingItem(item.value, item.kind, { precise: true, currency: baseCurrency })} (up from 0)`
    }
    if (item.changeFromPreviousPct === InfinityValue.NEGATIVE_INFINITY_VALUE) {
        return `${item.key}: new activity at ${formatMarketingItem(item.value, item.kind, { precise: true, currency: baseCurrency })} (down from 0)`
    }
    return null
}

// Helper for normal percentage change tooltip
const getNormalChangeTooltip = (item: MarketingAnalyticsItem, baseCurrency: string): string => {
    const direction = item.value! > item.previous! ? 'increased' : 'decreased'
    const percentageChange = percentage(Math.abs(item.changeFromPreviousPct!) / 100, 3)
    const currentValue = formatMarketingItem(item.value, item.kind, { precise: true, currency: baseCurrency })
    const previousValue = formatMarketingItem(item.previous, item.kind, { precise: true, currency: baseCurrency })

    return `${item.key}: ${direction} by ${percentageChange}, to ${currentValue} from ${previousValue}`
}

// Helper to create comparison tooltips
const createComparisonTooltip = (item: MarketingAnalyticsItem, baseCurrency: string): string => {
    const hasCurrentValue = isNotNil(item.value)
    const hasPreviousValue = isNotNil(item.previous)
    const hasChange = isNotNil(item.changeFromPreviousPct)

    // Full comparison with numeric values and change calculation
    if (
        hasCurrentValue &&
        hasPreviousValue &&
        hasChange &&
        typeof item.value === 'number' &&
        typeof item.previous === 'number'
    ) {
        const specialTooltip = getSpecialChangeTooltip(item, baseCurrency)
        return specialTooltip || getNormalChangeTooltip(item, baseCurrency)
    }

    // Both values but no change calculation
    if (hasCurrentValue && hasPreviousValue) {
        if (typeof item.value === 'string' || typeof item.previous === 'string') {
            return `${item.key}: ${item.value}`
        }
        return `${item.key}: ${formatMarketingItem(item.value, item.kind, { precise: true, currency: baseCurrency })} (previous: ${formatMarketingItem(item.previous, item.kind, { precise: true, currency: baseCurrency })})`
    }

    // Only current value
    if (hasCurrentValue && !hasPreviousValue) {
        return `${item.key}: ${formatMarketingItem(item.value, item.kind, { precise: true, currency: baseCurrency })} (no previous data for comparison)`
    }

    // Only previous value
    if (!hasCurrentValue && hasPreviousValue) {
        return `${item.key}: No current data (previous: ${formatMarketingItem(item.previous, item.kind, { precise: true, currency: baseCurrency })})`
    }

    return `${item.key}: No data available`
}

const getNoDataTooltip = (item: MarketingAnalyticsItem): string => {
    if (!item.hasComparison) {
        return `${item?.key || 'Value'}: ${item.value ?? 'N/A'}`
    }

    const hasCurrentValue = item?.value != null
    const hasPreviousValue = item?.previous != null

    if (!hasCurrentValue && !hasPreviousValue) {
        return `${item?.key || 'Value'}: no data available for current or previous period`
    } else if (!hasCurrentValue && hasPreviousValue) {
        return `${item?.key || 'Value'}: no data for current period (had data in previous period)`
    } else if (hasCurrentValue && !hasPreviousValue) {
        return `${item?.key || 'Value'}: no previous period data available for comparison`
    }

    return `${item?.key || 'Value'}: no data available`
}

// Helper to determine background color based on change and isIncreaseBad
const getChangeBackgroundColor = (
    changeFromPreviousPct: number | null | undefined,
    isIncreaseBad: boolean
): string | undefined => {
    if (!isNotNil(changeFromPreviousPct) || changeFromPreviousPct === 0) {
        return undefined // No background for no change
    }

    const isIncrease = changeFromPreviousPct > 0
    const isGood = isIncrease ? !isIncreaseBad : isIncreaseBad

    return isGood ? 'var(--color-bg-fill-success-highlight)' : 'var(--color-bg-fill-error-highlight)'
}

export const MarketingAnalyticsCell = ({ value: item }: { value: MarketingAnalyticsItem }): JSX.Element | null => {
    const { baseCurrency } = useValues(teamLogic)

    // Handle different no-data scenarios
    if (!item || (item.value == null && item.previous == null)) {
        return (
            <Tooltip title={getNoDataTooltip(item)} delayMs={300} className="cursor-default">
                <div
                    className="flex items-center justify-start min-w-0 cursor-default text-muted w-full hover:bg-warning-highlight"
                    style={{ maxWidth: '200px' }}
                >
                    <span className="overflow-hidden text-ellipsis whitespace-nowrap">-</span>
                </div>
            </Tooltip>
        )
    }

    // Handle case where we only have previous data but no current data
    if (item.value == null && item.previous != null) {
        const formattedPrevious = formatMarketingItem(item.previous, item.kind, {
            currency: baseCurrency,
            hideCurrency: true,
        })
        return (
            <Tooltip title={getNoDataTooltip(item)} delayMs={300} className="cursor-default">
                <div
                    className="flex flex-wrap min-w-0 cursor-default text-muted w-full hover:bg-warning-highlight"
                    style={{ maxWidth: '200px' }}
                >
                    <div className="min-w-0 overflow-hidden text-ellipsis whitespace-nowrap w-full">
                        ({formattedPrevious})
                        <IconTrendingFlat style={{ color: getColorVar('muted'), marginLeft: 4 }} />
                    </div>
                    <div className="w-full text-xs overflow-hidden text-ellipsis whitespace-nowrap">
                        Previous period
                    </div>
                </div>
            </Tooltip>
        )
    }

    // Determine trend icon and color based on change
    const trend = isNotNil(item.changeFromPreviousPct)
        ? item.changeFromPreviousPct === 0
            ? { Icon: IconTrendingFlat, color: getColorVar('muted') }
            : item.changeFromPreviousPct > 0
              ? {
                    Icon: IconTrending,
                    color: !item.isIncreaseBad ? getColorVar('success') : getColorVar('danger'),
                }
              : {
                    Icon: IconTrendingDown,
                    color: !item.isIncreaseBad ? getColorVar('danger') : getColorVar('success'),
                }
        : undefined

    // Create tooltip content
    const tooltip = !item.hasComparison
        ? `${item.key}: ${formatMarketingItem(item.value, item.kind, { precise: true, currency: baseCurrency })}`
        : createComparisonTooltip(item, baseCurrency)

    const formattedValue = formatMarketingItem(item.value, item.kind, { currency: baseCurrency, hideCurrency: true })
    const changePercFormatted = formatChangePercentage(item.changeFromPreviousPct)

    const bgColor = getChangeBackgroundColor(item.changeFromPreviousPct, item.isIncreaseBad ?? false)

    return (
        <Tooltip title={tooltip} delayMs={300} className="cursor-default">
            <div
                className="flex flex-wrap min-w-0 cursor-default w-full hover:bg-warning-highlight"
                style={{
                    backgroundColor: bgColor,
                    maxWidth: '200px',
                }}
            >
                <div className="min-w-0 overflow-hidden text-ellipsis whitespace-nowrap w-full">
                    {formattedValue}
                    {trend && <trend.Icon style={{ color: trend.color, marginLeft: 4 }} />}
                </div>
                {changePercFormatted && (
                    <div
                        className="w-full text-muted overflow-hidden text-ellipsis whitespace-nowrap"
                        style={{ color: trend?.color }}
                    >
                        {changePercFormatted}
                    </div>
                )}
            </div>
        </Tooltip>
    )
}
