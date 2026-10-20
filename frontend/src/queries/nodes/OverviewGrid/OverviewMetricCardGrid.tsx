import { useValues } from 'kea'
import type React from 'react'

import { IconWarning } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'
import { type ChartTheme, type MetricChange } from '@posthog/quill-charts'

import { AnalyticsMetricCard } from 'lib/components/AnalyticsMetricCard/AnalyticsMetricCard'
import { PreAggregatedBadge } from 'lib/components/PreAggregatedBadge'
import { dayjs } from 'lib/dayjs'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { range } from 'lib/utils/arrays'
import { cn } from 'lib/utils/css-classes'
import { teamLogic } from 'scenes/teamLogic'

import { WebAnalyticsPreComputeStrategy } from '~/queries/schema/schema-general'

import { formatItem, NO_BASELINE_CHANGE_SENTINEL, OverviewItem, SamplingNotice, SamplingRate } from './OverviewGrid'

export type OverviewMetricCardItem = OverviewItem & { sparkline?: { data: number[]; labels: string[] } }

interface OverviewMetricCardGridProps {
    items: OverviewMetricCardItem[]
    layout?: 'grid' | 'contents'
    loading: boolean
    numSkeletons: number
    emptyMessage?: React.ReactNode
    className?: string
    sparklineTheme?: ChartTheme
    samplingRate?: SamplingRate
    preComputeStrategy?: WebAnalyticsPreComputeStrategy
    onDisablePrecompute?: () => void
    labelFromKey: (key: string) => React.ReactNode
}

export function OverviewMetricCardGrid({
    items,
    layout = 'grid',
    loading,
    numSkeletons,
    emptyMessage,
    className,
    sparklineTheme,
    samplingRate,
    preComputeStrategy,
    onDisablePrecompute,
    labelFromKey,
}: OverviewMetricCardGridProps): JSX.Element {
    return (
        <>
            <div
                className={cn(
                    layout === 'contents' ? 'contents' : 'grid gap-2 grid-cols-[repeat(auto-fit,minmax(10rem,1fr))]',
                    className
                )}
            >
                {loading
                    ? range(numSkeletons).map((i) => <AnalyticsMetricCard key={i} title={null} loading />)
                    : items.map((item) => (
                          <MetricCardCell
                              key={item.key}
                              item={item}
                              sparklineTheme={sparklineTheme}
                              emptyMessage={emptyMessage}
                              stretch={layout === 'contents'}
                              preComputeStrategy={preComputeStrategy}
                              onDisablePrecompute={onDisablePrecompute}
                              labelFromKey={labelFromKey}
                          />
                      ))}
            </div>
            <SamplingNotice samplingRate={samplingRate} />
        </>
    )
}

function MetricCardCell({
    item,
    sparklineTheme,
    emptyMessage,
    stretch,
    preComputeStrategy,
    onDisablePrecompute,
    labelFromKey,
}: {
    item: OverviewMetricCardItem
    sparklineTheme?: ChartTheme
    emptyMessage?: React.ReactNode
    stretch?: boolean
    preComputeStrategy?: WebAnalyticsPreComputeStrategy
    onDisablePrecompute?: () => void
    labelFromKey: (key: string) => React.ReactNode
}): JSX.Element {
    const { baseCurrency } = useValues(teamLogic)

    const format = (n: number | string): string => formatItem(n, item.kind, { currency: baseCurrency })
    const subtitle = item.previous != null ? `vs. ${format(item.previous)} prior` : item.caption
    // MetricCard needs a numeric value to render text metrics through its formatter.
    const numericValue = typeof item.value === 'number' ? item.value : typeof item.value === 'string' ? 0 : undefined

    return (
        <AnalyticsMetricCard
            className={stretch ? 'h-full' : undefined}
            title={<MetricCardTitle label={labelFromKey(item.key)} item={item} />}
            onClick={item.onClick}
            selected={item.selected}
            value={numericValue}
            emptyMessage={emptyMessage}
            change={metricChange(item)}
            goodDirection={item.isIncreaseBad ? 'down' : 'up'}
            formatValue={(value) =>
                formatItem(typeof item.value === 'number' ? value : item.value, item.kind, { currency: baseCurrency })
            }
            subtitle={item.sparkline && sparklineTheme ? undefined : subtitle}
            restingSubtitle={subtitle}
            data={sparklineTheme ? item.sparkline?.data : undefined}
            labels={item.sparkline?.labels}
            theme={sparklineTheme}
            formatLabel={(label) => dayjs(label).format('MMM D')}
            sparklineHeight={48}
            sparklineClassName="mt-3"
            adornment={
                preComputeStrategy === WebAnalyticsPreComputeStrategy.LazyPrecompute ? (
                    <PreAggregatedBadge variant="precomputed" position="bottom-right" onDisable={onDisablePrecompute} />
                ) : preComputeStrategy === WebAnalyticsPreComputeStrategy.PreAggregated ? (
                    <PreAggregatedBadge variant="preagg" position="bottom-right" />
                ) : undefined
            }
        />
    )
}

function MetricCardTitle({ label, item }: { label: React.ReactNode; item: OverviewMetricCardItem }): JSX.Element {
    if (!item.warning) {
        return <>{label}</>
    }
    return (
        <span className="inline-flex items-center gap-1">
            {label}
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
        </span>
    )
}

function metricChange(item: OverviewMetricCardItem): MetricChange | null {
    if (
        item.changeFromPreviousPct == null ||
        item.changeFromPreviousPct === 0 ||
        Math.abs(item.changeFromPreviousPct) >= NO_BASELINE_CHANGE_SENTINEL
    ) {
        return null
    }
    return { value: item.changeFromPreviousPct }
}
