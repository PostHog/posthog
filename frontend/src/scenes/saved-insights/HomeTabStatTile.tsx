import clsx from 'clsx'
import { useValues } from 'kea'

import { LemonSkeleton } from '@posthog/lemon-ui'
import { MetricCard } from '@posthog/quill-charts'

import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { formatItem } from '~/queries/nodes/OverviewGrid/OverviewGrid'
import type { TrendsQueryResponse } from '~/queries/schema/schema-general'
import type { TrendResult } from '~/types'

import { getHomeTabStatValue, type HomeTabStatQuery } from './homeTabDefaultTiles'

interface HomeTabStatTileProps {
    stat: HomeTabStatQuery
    compare: boolean
    selected: boolean
    onSelect: () => void
}

export function HomeTabStatTile({ stat, compare, selected, onSelect }: HomeTabStatTileProps): JSX.Element {
    const key = `HomeTabStatTile.${stat.key}`
    const { response, responseError, responseLoading } = useValues(
        dataNodeLogic({ query: stat.query, key, dataNodeCollectionId: key })
    )
    const loading = responseLoading || (!response && !responseError)

    const results = (response as TrendsQueryResponse | undefined)?.results ?? (response as { result?: unknown })?.result
    const current = (results as TrendResult[] | undefined)?.[0]
    const previous = compare ? (results as TrendResult[] | undefined)?.[1] : undefined
    const value = getHomeTabStatValue(stat, current)
    const previousValue = getHomeTabStatValue(stat, previous)
    const changeFromPreviousPct =
        value != null && previousValue != null && previousValue !== 0
            ? ((value - previousValue) / Math.abs(previousValue)) * 100
            : undefined

    const label =
        stat.description || stat.key === 'session_duration' ? (
            <Tooltip title={stat.description ?? 'Average duration of sessions with a page or screen view.'}>
                {stat.title}
            </Tooltip>
        ) : (
            stat.title
        )

    let content: JSX.Element
    if (loading) {
        content = (
            <span className="flex w-full flex-col gap-2">
                <LemonSkeleton className="h-3 w-16" />
                <LemonSkeleton className="h-9 w-24" />
                <LemonSkeleton className="h-3 w-24" />
            </span>
        )
    } else if (responseError) {
        content = <span className="text-sm text-danger">Could not load</span>
    } else if (value == null) {
        content = <span className="text-sm text-secondary">No data for this period</span>
    } else {
        let subtitle: string
        if (!compare) {
            subtitle = 'For selected period'
        } else if (previousValue == null) {
            subtitle = 'No previous period data'
        } else {
            subtitle = `vs. ${formatItem(previousValue, stat.kind)} prior`
        }

        content = (
            <MetricCard
                title={<span className={selected ? 'text-accent' : undefined}>{label}</span>}
                value={value}
                change={changeFromPreviousPct ? { value: changeFromPreviousPct } : null}
                goodDirection="up"
                formatValue={(statValue) => formatItem(statValue, stat.kind)}
                subtitle={<span translate="no">{subtitle}</span>}
            />
        )
    }

    return (
        <button
            type="button"
            onClick={onSelect}
            aria-pressed={selected}
            aria-busy={loading}
            data-attr={`home-tab-metric-${stat.key}`}
            className={clsx(
                'relative flex h-full w-full min-w-0 flex-col rounded border p-3 text-left transition-colors focus-visible:ring-2 focus-visible:ring-accent',
                selected
                    ? 'border-accent bg-accent-highlight-secondary'
                    : 'border-primary bg-surface-primary hover:border-accent'
            )}
        >
            {!loading && (responseError || value == null) && <span className="mb-2 text-sm font-medium">{label}</span>}
            {content}
        </button>
    )
}
