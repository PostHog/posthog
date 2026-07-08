import clsx from 'clsx'
import { useValues } from 'kea'
import type React from 'react'

import { IconTrending, IconWarning } from '@posthog/icons'
import { LemonBanner, LemonSkeleton, Link } from '@posthog/lemon-ui'

import { getColorVar } from 'lib/colors'
import { PreAggregatedBadge } from 'lib/components/PreAggregatedBadge'
import { IconTrendingDown, IconTrendingFlat } from 'lib/lemon-ui/icons'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { range } from 'lib/utils/arrays'
import { DEFAULT_CURRENCY, getCurrencySymbol } from 'lib/utils/currency'
import { humanFriendlyDuration } from 'lib/utils/durations'
import { isNotNil } from 'lib/utils/guards'
import { formatPercentage, humanFriendlyLargeNumber } from 'lib/utils/numbers'
import { teamLogic } from 'scenes/teamLogic'

import { EvenlyDistributedRows } from '~/queries/nodes/WebOverview/EvenlyDistributedRows'
import { WebAnalyticsItemKind, WebAnalyticsPreComputeStrategy } from '~/queries/schema/schema-general'

export const NO_BASELINE_CHANGE_SENTINEL = 999999

const OVERVIEW_ITEM_CELL_MIN_WIDTH_REMS_COMPACT = 6
const OVERVIEW_ITEM_CELL_MIN_WIDTH_REMS_DEFAULT = 10

// Default classes for non-compact mode
const OVERVIEW_ITEM_CELL_CLASSES_DEFAULT = `flex-1 border p-2 bg-surface-primary rounded min-w-[10rem] h-30 flex flex-col items-center text-center justify-between`

// Compact classes for marketing analytics
const OVERVIEW_ITEM_CELL_CLASSES_COMPACT = `flex-1 border p-1 bg-surface-primary rounded min-w-[6rem] h-24 flex flex-col items-center text-center justify-between`

export interface OverviewItem {
    key: string
    value: number | string | undefined
    previous?: number | string | undefined
    changeFromPreviousPct?: number | undefined
    kind: WebAnalyticsItemKind
    isIncreaseBad?: boolean
    warning?: string
    warningLink?: string
    /** Optional human-readable description rendered under the value. Only shown when no trend is present. */
    caption?: string
    /** Click handler. When set, the cell renders as a button and shows a pointer cursor. */
    onClick?: () => void
    /** Render with the highlighted/active appearance — e.g. when this tile drives an active filter. */
    selected?: boolean
}

export interface SamplingRate {
    numerator: number
    denominator?: number
}

interface OverviewGridProps {
    items: OverviewItem[]
    loading: boolean
    numSkeletons: number
    samplingRate?: SamplingRate
    preComputeStrategy?: WebAnalyticsPreComputeStrategy
    onDisablePrecompute?: () => void
    labelFromKey: (key: string) => string
    filterEmptyItems?: (item: OverviewItem) => boolean
    compact?: boolean
}

export function OverviewGrid({
    items,
    loading,
    numSkeletons,
    samplingRate,
    preComputeStrategy,
    onDisablePrecompute,
    labelFromKey,
    filterEmptyItems = () => true,
    compact = false,
}: OverviewGridProps): JSX.Element {
    const filteredItems = items.filter(filterEmptyItems)

    return (
        <>
            <EvenlyDistributedRows
                className={`flex justify-center items-center flex-wrap w-full ${compact ? 'gap-1' : 'gap-2'}`}
                minWidthRems={
                    compact
                        ? OVERVIEW_ITEM_CELL_MIN_WIDTH_REMS_COMPACT + 1
                        : OVERVIEW_ITEM_CELL_MIN_WIDTH_REMS_DEFAULT + 2
                }
                maxItemsPerRow={compact ? 10 : undefined}
            >
                {loading
                    ? range(numSkeletons).map((i) => <OverviewItemCellSkeleton key={i} compact={compact} />)
                    : filteredItems.map((item) => (
                          <OverviewItemCell
                              key={item.key}
                              item={item}
                              preComputeStrategy={preComputeStrategy}
                              onDisablePrecompute={onDisablePrecompute}
                              labelFromKey={labelFromKey}
                              compact={compact}
                          />
                      ))}
            </EvenlyDistributedRows>
            <SamplingNotice samplingRate={samplingRate} />
        </>
    )
}

export function SamplingNotice({ samplingRate }: { samplingRate?: SamplingRate }): JSX.Element | null {
    if (!samplingRate || (samplingRate.numerator === 1 && (samplingRate.denominator ?? 1) === 1)) {
        return null
    }
    return (
        <LemonBanner type="info" className="my-4">
            These results are using a sampling factor of {samplingRate.numerator}
            <span>{(samplingRate.denominator ?? 1) !== 1 ? `/${samplingRate.denominator}` : ''}</span>. Sampling is
            currently in beta.
        </LemonBanner>
    )
}

const OverviewItemCellSkeleton = ({ compact }: { compact: boolean }): JSX.Element => {
    const cellClasses = compact ? OVERVIEW_ITEM_CELL_CLASSES_COMPACT : OVERVIEW_ITEM_CELL_CLASSES_DEFAULT
    return (
        <div className={cellClasses}>
            <div className="flex flex-row w-full">
                <div className="flex flex-row items-start justify-start flex-1">
                    {/* Empty space for potential beta tag */}
                </div>
                <div className={`uppercase py-0.5 ${compact ? 'text-[10px]' : 'text-xs font-bold'}`}>
                    <LemonSkeleton className={`w-16 ${compact ? 'h-2.5' : 'h-3'}`} />
                </div>
                <div className="flex flex-1 flex-row justify-end items-start">
                    {/* Empty space for potential action buttons */}
                </div>
            </div>
            <div className="w-full flex-1 flex items-center justify-center">
                <LemonSkeleton className="h-6 w-20" />
            </div>
            <div className="flex items-center justify-center">
                <LemonSkeleton className="h-4 w-12" />
            </div>
        </div>
    )
}

interface OverviewItemCellProps {
    item: OverviewItem
    preComputeStrategy?: WebAnalyticsPreComputeStrategy
    onDisablePrecompute?: () => void
    labelFromKey: (key: string) => string
    compact: boolean
}

const OverviewItemCell = ({
    item,
    preComputeStrategy,
    onDisablePrecompute,
    labelFromKey,
    compact,
}: OverviewItemCellProps): JSX.Element => {
    const { baseCurrency } = useValues(teamLogic)

    const label = labelFromKey(item.key)

    const trend =
        isNotNil(item.changeFromPreviousPct) && Math.abs(item.changeFromPreviousPct) < NO_BASELINE_CHANGE_SENTINEL
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

    // Handle tooltip logic with special cases for zero values and small changes
    const tooltip =
        isNotNil(item.value) &&
        isNotNil(item.previous) &&
        isNotNil(item.changeFromPreviousPct) &&
        Math.abs(item.changeFromPreviousPct) < NO_BASELINE_CHANGE_SENTINEL
            ? item.value === 0 && item.previous === 0
                ? `${label}: No change (0 in both periods)`
                : Math.abs(item.changeFromPreviousPct) < 1
                  ? `${label}: No impactful change, less than 1%`
                  : `${label}: ${item.value >= item.previous ? 'increased' : 'decreased'} by ${formatPercentage(
                        Math.abs(item.changeFromPreviousPct),
                        { precise: true }
                    )}, to ${formatItem(item.value, item.kind, { precise: true, currency: baseCurrency })} from ${formatItem(
                        item.previous,
                        item.kind,
                        { precise: true, currency: baseCurrency }
                    )}`
            : isNotNil(item.value) &&
                isNotNil(item.previous) &&
                Math.abs(item.changeFromPreviousPct || 0) >= NO_BASELINE_CHANGE_SENTINEL
              ? `${label}: ${formatItem(item.value, item.kind, { precise: true, currency: baseCurrency })} (was 0 in previous period)`
              : isNotNil(item.value)
                ? `${label}: ${formatItem(item.value, item.kind, { precise: true, currency: baseCurrency })}`
                : 'No data'

    const clickable = !!item.onClick
    const handleClick = clickable
        ? (event: React.MouseEvent) => {
              event.stopPropagation()
              item.onClick?.()
          }
        : undefined
    const handleKeyDown = clickable
        ? (event: React.KeyboardEvent) => {
              if (event.key === 'Enter' || event.key === ' ') {
                  event.preventDefault()
                  item.onClick?.()
              }
          }
        : undefined

    return (
        <div
            className={clsx(
                'flex-1 border bg-surface-primary rounded relative transition-colors',
                compact ? 'min-w-[6rem] h-24' : 'min-w-[10rem] h-30',
                item.selected && 'border-accent ring-1 ring-accent',
                clickable && 'cursor-pointer hover:border-accent'
            )}
            onClick={handleClick}
            onKeyDown={handleKeyDown}
            role={clickable ? 'button' : undefined}
            tabIndex={clickable ? 0 : undefined}
            aria-pressed={clickable ? !!item.selected : undefined}
        >
            {/* Rendered as a sibling of the Tooltip trigger so hovering the badge
                does not also surface the cell's metric tooltip. */}
            {preComputeStrategy === WebAnalyticsPreComputeStrategy.LazyPrecompute ? (
                <PreAggregatedBadge variant="precomputed" onDisable={onDisablePrecompute} />
            ) : preComputeStrategy === WebAnalyticsPreComputeStrategy.PreAggregated ? (
                <PreAggregatedBadge variant="preagg" />
            ) : null}
            <Tooltip title={tooltip}>
                <div
                    className={clsx(
                        'flex flex-col items-center text-center justify-between w-full h-full',
                        compact ? 'p-1' : 'p-2'
                    )}
                >
                    <div className="flex flex-row w-full justify-center items-center gap-1">
                        <div className={`uppercase py-0.5 ${compact ? 'text-[10px]' : 'text-xs font-bold'}`}>
                            {label}
                        </div>
                        {item.warning && (
                            <Tooltip
                                interactive={!!item.warningLink}
                                title={
                                    <div>
                                        {item.warning}
                                        {item.warningLink && (
                                            <>
                                                {' '}
                                                <Link to={item.warningLink} className="text-link">
                                                    Learn more
                                                </Link>
                                            </>
                                        )}
                                    </div>
                                }
                            >
                                <IconWarning className="text-warning h-3.5 w-3.5 cursor-pointer" />
                            </Tooltip>
                        )}
                    </div>
                    <div className="w-full flex-1 flex items-center justify-center">
                        <div className={compact ? 'text-lg' : 'text-2xl'}>
                            {formatItem(item.value, item.kind, { currency: baseCurrency })}
                        </div>
                    </div>
                    {trend && isNotNil(item.changeFromPreviousPct) ? (
                        // eslint-disable-next-line react/forbid-dom-props
                        <div style={{ color: trend.color }}>
                            <trend.Icon color={trend.color} />
                            {formatPercentage(item.changeFromPreviousPct)}
                        </div>
                    ) : isNotNil(item.changeFromPreviousPct) &&
                      Math.abs(item.changeFromPreviousPct) >= NO_BASELINE_CHANGE_SENTINEL ? (
                        <div className="text-muted">-</div>
                    ) : item.caption ? (
                        <div
                            className={clsx('text-secondary truncate max-w-full', compact ? 'text-[10px]' : 'text-xs')}
                            title={item.caption}
                        >
                            {item.caption}
                        </div>
                    ) : (
                        <div />
                    )}
                </div>
            </Tooltip>
        </div>
    )
}

const formatUnit = (x: number, options?: { precise?: boolean }): string => {
    if (options?.precise) {
        return x.toLocaleString()
    }
    return humanFriendlyLargeNumber(x)
}

export const formatItem = (
    value: number | string | undefined,
    kind: WebAnalyticsItemKind,
    options?: { precise?: boolean; currency?: string }
): string => {
    if (value == null) {
        return '-'
    }

    if (typeof value === 'string') {
        return value
    }

    if (kind === 'percentage') {
        return formatPercentage(value, { precise: options?.precise })
    } else if (kind === 'duration_s') {
        return humanFriendlyDuration(value, { secondsPrecision: 3 })
    } else if (kind === 'currency') {
        const { symbol, isPrefix } = getCurrencySymbol(options?.currency ?? DEFAULT_CURRENCY)
        return `${isPrefix ? symbol : ''}${formatUnit(value, { precise: options?.precise })}${
            isPrefix ? '' : ' ' + symbol
        }`
    }
    return formatUnit(value, options)
}
