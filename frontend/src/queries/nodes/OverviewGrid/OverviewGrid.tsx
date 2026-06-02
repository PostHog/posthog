import clsx from 'clsx'
import { useValues } from 'kea'
import { Fragment } from 'react'

import { IconTrending, IconWarning } from '@posthog/icons'
import { LemonBanner, LemonSkeleton, Link } from '@posthog/lemon-ui'

import { getColorVar } from 'lib/colors'
import { PreAggregatedBadge } from 'lib/components/PreAggregatedBadge'
import { IconTrendingDown, IconTrendingFlat } from 'lib/lemon-ui/icons'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { formatPercentage, humanFriendlyDuration, humanFriendlyLargeNumber, isNotNil, range } from 'lib/utils'
import { DEFAULT_CURRENCY, getCurrencySymbol } from 'lib/utils/geography/currency'
import { teamLogic } from 'scenes/teamLogic'

import { EvenlyDistributedRows } from '~/queries/nodes/WebOverview/EvenlyDistributedRows'
import { WebAnalyticsItemKind } from '~/queries/schema/schema-general'

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
    usedPreAggregatedTables?: boolean
    usedLazyPrecompute?: boolean
    labelFromKey: (key: string) => string
    filterEmptyItems?: (item: OverviewItem) => boolean
    compact?: boolean
    /** Optional override for how each item is rendered. When omitted, the default centered cell is used. */
    renderItem?: (item: OverviewItem, helpers: OverviewItemRenderHelpers) => JSX.Element
}

export interface OverviewItemRenderHelpers {
    label: string
    usedPreAggregatedTables: boolean
    usedLazyPrecompute: boolean
    compact: boolean
}

export function OverviewGrid({
    items,
    loading,
    numSkeletons,
    samplingRate,
    usedPreAggregatedTables = false,
    usedLazyPrecompute = false,
    labelFromKey,
    filterEmptyItems = () => true,
    compact = false,
    renderItem,
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
                    : filteredItems.map((item) =>
                          renderItem ? (
                              <Fragment key={item.key}>
                                  {renderItem(item, {
                                      label: labelFromKey(item.key),
                                      usedPreAggregatedTables,
                                      usedLazyPrecompute,
                                      compact,
                                  })}
                              </Fragment>
                          ) : (
                              <OverviewItemCell
                                  key={item.key}
                                  item={item}
                                  usedPreAggregatedTables={usedPreAggregatedTables}
                                  usedLazyPrecompute={usedLazyPrecompute}
                                  labelFromKey={labelFromKey}
                                  compact={compact}
                              />
                          )
                      )}
            </EvenlyDistributedRows>
            {samplingRate && !(samplingRate.numerator === 1 && (samplingRate.denominator ?? 1) === 1) ? (
                <LemonBanner type="info" className="my-4">
                    These results are using a sampling factor of {samplingRate.numerator}
                    <span>{(samplingRate.denominator ?? 1 !== 1) ? `/${samplingRate.denominator}` : ''}</span>. Sampling
                    is currently in beta.
                </LemonBanner>
            ) : null}
        </>
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
    usedPreAggregatedTables: boolean
    usedLazyPrecompute: boolean
    labelFromKey: (key: string) => string
    compact: boolean
}

const OverviewItemCell = ({
    item,
    usedPreAggregatedTables,
    usedLazyPrecompute,
    labelFromKey,
    compact,
}: OverviewItemCellProps): JSX.Element => {
    const { baseCurrency } = useValues(teamLogic)

    const label = labelFromKey(item.key)

    const trend =
        isNotNil(item.changeFromPreviousPct) && Math.abs(item.changeFromPreviousPct) < 999999
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

    const tooltip = getOverviewItemTooltip(item, label, baseCurrency)

    return (
        <div
            className={clsx(
                'flex-1 border bg-surface-primary rounded relative',
                compact ? 'min-w-[6rem] h-24' : 'min-w-[10rem] h-30'
            )}
        >
            {/* Rendered as a sibling of the Tooltip trigger so hovering the badge
                does not also surface the cell's metric tooltip. */}
            {usedLazyPrecompute ? (
                <PreAggregatedBadge variant="precomputed" />
            ) : usedPreAggregatedTables ? (
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
                    ) : isNotNil(item.changeFromPreviousPct) && Math.abs(item.changeFromPreviousPct) >= 999999 ? (
                        <div className="text-muted">-</div>
                    ) : (
                        <div />
                    )}
                </div>
            </Tooltip>
        </div>
    )
}

// Builds the hover tooltip for an overview metric, with special cases for zero values and small changes
export const getOverviewItemTooltip = (item: OverviewItem, label: string, currency: string): string => {
    if (
        isNotNil(item.value) &&
        isNotNil(item.previous) &&
        isNotNil(item.changeFromPreviousPct) &&
        Math.abs(item.changeFromPreviousPct) < 999999
    ) {
        if (item.value === 0 && item.previous === 0) {
            return `${label}: No change (0 in both periods)`
        }
        if (Math.abs(item.changeFromPreviousPct) < 1) {
            return `${label}: No impactful change, less than 1%`
        }
        return `${label}: ${item.value >= item.previous ? 'increased' : 'decreased'} by ${formatPercentage(
            Math.abs(item.changeFromPreviousPct),
            { precise: true }
        )}, to ${formatItem(item.value, item.kind, { precise: true, currency })} from ${formatItem(item.previous, item.kind, {
            precise: true,
            currency,
        })}`
    }
    if (isNotNil(item.value) && isNotNil(item.previous) && Math.abs(item.changeFromPreviousPct || 0) >= 999999) {
        return `${label}: ${formatItem(item.value, item.kind, { precise: true, currency })} (was 0 in previous period)`
    }
    if (isNotNil(item.value)) {
        return `${label}: ${formatItem(item.value, item.kind, { precise: true, currency })}`
    }
    return 'No data'
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
