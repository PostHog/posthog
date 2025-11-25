import clsx from 'clsx'
import { useValues } from 'kea'

import { IconDashboard, IconGear, IconTrending } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSkeleton, LemonTag } from '@posthog/lemon-ui'

import { getColorVar } from 'lib/colors'
import { PreAggregatedBadge } from 'lib/components/PreAggregatedBadge'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { IconTrendingDown, IconTrendingFlat } from 'lib/lemon-ui/icons'
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
    labelFromKey: (key: string) => string
    settingsLinkFromKey: (key: string) => string | null
    dashboardLinkFromKey: (key: string) => string | null
    filterEmptyItems?: (item: OverviewItem) => boolean
    showBetaTags?: (key: string) => boolean
    compact?: boolean
}

export function OverviewGrid({
    items,
    loading,
    numSkeletons,
    samplingRate,
    usedPreAggregatedTables = false,
    labelFromKey,
    settingsLinkFromKey,
    dashboardLinkFromKey,
    filterEmptyItems = () => true,
    showBetaTags = () => false,
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
                              usedPreAggregatedTables={usedPreAggregatedTables}
                              labelFromKey={labelFromKey}
                              settingsLinkFromKey={settingsLinkFromKey}
                              dashboardLinkFromKey={dashboardLinkFromKey}
                              showBetaTag={showBetaTags(item.key)}
                              compact={compact}
                          />
                      ))}
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
    labelFromKey: (key: string) => string
    settingsLinkFromKey: (key: string) => string | null
    dashboardLinkFromKey: (key: string) => string | null
    showBetaTag: boolean
    compact: boolean
}

const OverviewItemCell = ({
    item,
    usedPreAggregatedTables,
    labelFromKey,
    settingsLinkFromKey,
    dashboardLinkFromKey,
    showBetaTag,
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

    const docsUrl = settingsLinkFromKey(item.key)
    const dashboardUrl = dashboardLinkFromKey(item.key)

    // Handle tooltip logic with special cases for zero values and small changes
    const tooltip =
        isNotNil(item.value) &&
        isNotNil(item.previous) &&
        isNotNil(item.changeFromPreviousPct) &&
        Math.abs(item.changeFromPreviousPct) < 999999
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
            : isNotNil(item.value) && isNotNil(item.previous) && Math.abs(item.changeFromPreviousPct || 0) >= 999999
              ? `${label}: ${formatItem(item.value, item.kind, { precise: true, currency: baseCurrency })} (was 0 in previous period)`
              : isNotNil(item.value)
                ? `${label}: ${formatItem(item.value, item.kind, { precise: true, currency: baseCurrency })}`
                : 'No data'

    return (
        <Tooltip title={tooltip}>
            <div
                className={clsx(
                    compact ? OVERVIEW_ITEM_CELL_CLASSES_COMPACT : OVERVIEW_ITEM_CELL_CLASSES_DEFAULT,
                    'relative'
                )}
            >
                {usedPreAggregatedTables && <PreAggregatedBadge />}
                <div className="flex flex-row w-full">
                    <div className="flex flex-row items-start justify-start flex-1">
                        {/* NOTE: If we ever decide to remove the beta tag, make sure we keep an empty div with flex-1 to keep the layout consistent */}
                        {showBetaTag && <LemonTag type="warning">BETA</LemonTag>}
                    </div>
                    <div className={`uppercase py-0.5 ${compact ? 'text-[10px]' : 'text-xs font-bold'}`}>
                        {label}&nbsp;
                    </div>
                    <div className="flex flex-1 flex-row justify-end items-start">
                        {dashboardUrl && (
                            <Tooltip title={`Access dedicated ${item.key} dashboard`}>
                                <LemonButton to={dashboardUrl} icon={<IconDashboard />} size="xsmall" targetBlank />
                            </Tooltip>
                        )}
                        {docsUrl && (
                            <Tooltip title={`Access ${item.key} settings`}>
                                <LemonButton to={docsUrl} icon={<IconGear />} size="xsmall" />
                            </Tooltip>
                        )}
                    </div>
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
    )
}

const formatUnit = (x: number, options?: { precise?: boolean }): string => {
    if (options?.precise) {
        return x.toLocaleString()
    }
    return humanFriendlyLargeNumber(x)
}

const formatItem = (
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
