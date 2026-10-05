import clsx from 'clsx'
import { useValues } from 'kea'

import { LemonSkeleton } from '@posthog/lemon-ui'

import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { formatPercentage } from 'lib/utils/numbers'

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
    if (responseLoading || (!response && !responseError)) {
        content = (
            <>
                <LemonSkeleton className="h-7 w-20" />
                <LemonSkeleton className="h-3 w-24" />
            </>
        )
    } else if (responseError) {
        content = <span className="text-sm text-danger">Could not load</span>
    } else if (value == null) {
        content = <span className="text-sm text-secondary">No data for this period</span>
    } else {
        let comparison: string
        if (!compare) {
            comparison = 'For selected period'
        } else if (previousValue == null) {
            comparison = 'No previous period data'
        } else if (previousValue === 0) {
            comparison = value === 0 ? 'No change vs prior' : 'New vs prior period'
        } else if (changeFromPreviousPct === 0) {
            comparison = 'No change vs prior'
        } else if (changeFromPreviousPct != null) {
            comparison = `${changeFromPreviousPct > 0 ? '↑' : '↓'} ${formatPercentage(Math.abs(changeFromPreviousPct), {
                compact: true,
            })} vs prior`
        } else {
            comparison = 'No comparison data'
        }

        content = (
            <>
                <span className="w-full truncate text-2xl font-semibold leading-tight tabular-nums" translate="no">
                    {formatItem(value, stat.kind)}
                </span>
                <Tooltip
                    title={
                        previousValue != null ? `${formatItem(previousValue, stat.kind)} in previous period` : undefined
                    }
                >
                    <span className="w-full truncate text-xs text-secondary" translate="no">
                        {comparison}
                    </span>
                </Tooltip>
            </>
        )
    }

    return (
        <button
            type="button"
            onClick={onSelect}
            aria-pressed={selected}
            aria-busy={responseLoading || (!response && !responseError)}
            data-attr={`home-tab-metric-${stat.key}`}
            className={clsx(
                'relative flex h-full min-h-24 w-full min-w-0 flex-col items-start gap-2 rounded border px-3 py-3 text-left transition-colors focus-visible:ring-2 focus-visible:ring-accent',
                selected
                    ? 'border-accent bg-accent-highlight-secondary'
                    : 'border-primary bg-surface-primary hover:border-accent'
            )}
        >
            <span className={clsx('w-full text-xs font-medium', selected ? 'text-accent' : 'text-secondary')}>
                {label}
            </span>
            <span className="flex w-full min-w-0 flex-col gap-1">{content}</span>
        </button>
    )
}
