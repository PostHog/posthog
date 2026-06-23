import clsx from 'clsx'
import { useValues } from 'kea'
import type React from 'react'

import { IconWarning } from '@posthog/icons'
import { LemonSkeleton, Link } from '@posthog/lemon-ui'
import { MetricCard, type MetricChange } from '@posthog/quill-charts'

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
    loading: boolean
    numSkeletons: number
    samplingRate?: SamplingRate
    preComputeStrategy?: WebAnalyticsPreComputeStrategy
    onDisablePrecompute?: () => void
    labelFromKey: (key: string) => string
}

export function OverviewMetricCardGrid({
    items,
    loading,
    numSkeletons,
    samplingRate,
    preComputeStrategy,
    onDisablePrecompute,
    labelFromKey,
}: OverviewMetricCardGridProps): JSX.Element {
    return (
        <>
            <div className="grid gap-2 grid-cols-[repeat(auto-fit,minmax(10rem,1fr))]">
                {loading
                    ? range(numSkeletons).map((i) => <MetricCardSkeleton key={i} />)
                    : items.map((item) => (
                          <MetricCardCell
                              key={item.key}
                              item={item}
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
    preComputeStrategy,
    onDisablePrecompute,
    labelFromKey,
}: {
    item: OverviewMetricCardItem
    preComputeStrategy?: WebAnalyticsPreComputeStrategy
    onDisablePrecompute?: () => void
    labelFromKey: (key: string) => string
}): JSX.Element {
    const { baseCurrency } = useValues(teamLogic)

    const format = (n: number): string => formatItem(n, item.kind, { currency: baseCurrency })
    const subtitle = item.previous != null ? `vs. ${format(item.previous)} prior` : item.caption

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
                'relative flex flex-col rounded border bg-surface-primary p-3 transition-colors',
                item.selected && 'border-accent ring-1 ring-accent',
                clickable && 'cursor-pointer hover:border-accent'
            )}
            onClick={handleClick}
            onKeyDown={handleKeyDown}
            role={clickable ? 'button' : undefined}
            tabIndex={clickable ? 0 : undefined}
            aria-pressed={clickable ? !!item.selected : undefined}
        >
            {preComputeStrategy === WebAnalyticsPreComputeStrategy.LazyPrecompute ? (
                <PreAggregatedBadge variant="precomputed" position="bottom-right" onDisable={onDisablePrecompute} />
            ) : preComputeStrategy === WebAnalyticsPreComputeStrategy.PreAggregated ? (
                <PreAggregatedBadge variant="preagg" position="bottom-right" />
            ) : null}
            <MetricCard
                title={<MetricCardTitle label={labelFromKey(item.key)} item={item} />}
                value={item.value}
                change={metricChange(item)}
                goodDirection={item.isIncreaseBad ? 'down' : 'up'}
                formatValue={format}
                subtitle={subtitle}
            />
        </div>
    )
}

function MetricCardTitle({ label, item }: { label: string; item: OverviewMetricCardItem }): JSX.Element {
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

function MetricCardSkeleton(): JSX.Element {
    return (
        <div className="flex flex-col gap-2 rounded border bg-surface-primary p-3">
            <LemonSkeleton className="h-3 w-16" />
            <LemonSkeleton className="h-9 w-24" />
            <LemonSkeleton className="h-3 w-20" />
        </div>
    )
}
