import { useValues } from 'kea'
import type React from 'react'

import { IconWarning } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'
import { type MetricChange } from '@posthog/quill-charts'

import { AnalyticsMetricCard } from 'lib/components/AnalyticsMetricCard/AnalyticsMetricCard'
import { PreAggregatedBadge } from 'lib/components/PreAggregatedBadge'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { range } from 'lib/utils/arrays'
import { teamLogic } from 'scenes/teamLogic'

import { WebAnalyticsPreComputeStrategy } from '~/queries/schema/schema-general'

import { formatItem, NO_BASELINE_CHANGE_SENTINEL, OverviewItem, SamplingNotice, SamplingRate } from './OverviewGrid'

export interface OverviewMetricCardItem extends Omit<OverviewItem, 'value' | 'previous'> {
    value: number | undefined
    previous?: number
}

interface OverviewMetricCardGridProps {
    items: OverviewMetricCardItem[]
    layout?: 'grid' | 'contents'
    loading: boolean
    numSkeletons: number
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
    samplingRate,
    preComputeStrategy,
    onDisablePrecompute,
    labelFromKey,
}: OverviewMetricCardGridProps): JSX.Element {
    return (
        <>
            <div
                className={
                    layout === 'contents' ? 'contents' : 'grid gap-2 grid-cols-[repeat(auto-fit,minmax(10rem,1fr))]'
                }
            >
                {loading
                    ? range(numSkeletons).map((i) => <AnalyticsMetricCard key={i} title={null} loading />)
                    : items.map((item) => (
                          <MetricCardCell
                              key={item.key}
                              item={item}
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
    stretch,
    preComputeStrategy,
    onDisablePrecompute,
    labelFromKey,
}: {
    item: OverviewMetricCardItem
    stretch?: boolean
    preComputeStrategy?: WebAnalyticsPreComputeStrategy
    onDisablePrecompute?: () => void
    labelFromKey: (key: string) => React.ReactNode
}): JSX.Element {
    const { baseCurrency } = useValues(teamLogic)

    const format = (n: number): string => formatItem(n, item.kind, { currency: baseCurrency })
    const subtitle = item.previous != null ? `vs. ${format(item.previous)} prior` : item.caption

    return (
        <AnalyticsMetricCard
            className={stretch ? 'h-full' : undefined}
            title={<MetricCardTitle label={labelFromKey(item.key)} item={item} />}
            onClick={item.onClick}
            selected={item.selected}
            value={item.value}
            change={metricChange(item)}
            goodDirection={item.isIncreaseBad ? 'down' : 'up'}
            formatValue={format}
            subtitle={subtitle}
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
