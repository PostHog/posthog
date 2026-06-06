import { useValues } from 'kea'

import { IconWarning } from '@posthog/icons'
import { LemonSkeleton, Link } from '@posthog/lemon-ui'
import { MetricCard, type MetricChange } from '@posthog/quill-charts'

import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { range } from 'lib/utils'
import { teamLogic } from 'scenes/teamLogic'

import { formatItem, OverviewItem, SamplingNotice, SamplingRate } from './OverviewGrid'

// The backend's change percentage uses this magnitude as a sentinel for "previous period was zero".
const NO_BASELINE_CHANGE_SENTINEL = 999999

interface OverviewMetricCardGridProps {
    items: OverviewItem[]
    loading: boolean
    numSkeletons: number
    samplingRate?: SamplingRate
    labelFromKey: (key: string) => string
}

export function OverviewMetricCardGrid({
    items,
    loading,
    numSkeletons,
    samplingRate,
    labelFromKey,
}: OverviewMetricCardGridProps): JSX.Element {
    return (
        <>
            <div className="grid gap-2 grid-cols-[repeat(auto-fit,minmax(10rem,1fr))]">
                {loading
                    ? range(numSkeletons).map((i) => <MetricCardSkeleton key={i} />)
                    : items.map((item) => <MetricCardCell key={item.key} item={item} labelFromKey={labelFromKey} />)}
            </div>
            <SamplingNotice samplingRate={samplingRate} />
        </>
    )
}

function MetricCardCell({
    item,
    labelFromKey,
}: {
    item: OverviewItem
    labelFromKey: (key: string) => string
}): JSX.Element {
    const { baseCurrency } = useValues(teamLogic)

    const value = typeof item.value === 'number' ? item.value : undefined
    const previous = typeof item.previous === 'number' ? item.previous : undefined
    const format = (n: number): string => formatItem(n, item.kind, { currency: baseCurrency })

    return (
        <div className="flex flex-col rounded border bg-surface-primary p-3">
            <MetricCard
                title={<MetricCardTitle label={labelFromKey(item.key)} item={item} />}
                value={value}
                change={metricChange(item)}
                goodDirection={item.isIncreaseBad ? 'down' : 'up'}
                formatValue={format}
                subtitle={previous != null ? `vs. ${format(previous)} prior` : undefined}
            />
        </div>
    )
}

function MetricCardTitle({ label, item }: { label: string; item: OverviewItem }): JSX.Element {
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

function metricChange(item: OverviewItem): MetricChange | null {
    if (item.changeFromPreviousPct == null || Math.abs(item.changeFromPreviousPct) >= NO_BASELINE_CHANGE_SENTINEL) {
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
