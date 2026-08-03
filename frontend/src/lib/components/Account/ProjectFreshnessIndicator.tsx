import { dayjs } from 'lib/dayjs'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { cn } from 'lib/utils/css-classes'

import type {
    DataFreshnessProjectApi,
    DataFreshnessSourceApi,
    DataSourceEnumApi,
} from 'products/platform_features/frontend/generated/api.schemas'

const DATA_SOURCE_LABELS: Record<DataSourceEnumApi, string> = {
    product_analytics: 'Product analytics',
    session_replay: 'Session replay',
    error_tracking: 'Error tracking',
    llm_analytics: 'LLM analytics',
    surveys: 'Surveys',
    feature_flags: 'Feature flags',
    logs: 'Logs',
    apm: 'Tracing',
    destinations: 'Destinations',
    messaging: 'Messaging',
    data_warehouse: 'Data warehouse',
}

/**
 * Compact enough to sit in a menu row without crowding the project name, and unit-unambiguous
 * so a column of them can be compared at a glance. Notably `mo` rather than `m`, which would
 * read as minutes next to `1y`.
 */
function compactAge(timestamp: string): string {
    const then = dayjs(timestamp)
    if (dayjs().diff(then, 'minute') < 60) {
        return 'now'
    }
    const hours = dayjs().diff(then, 'hour')
    if (hours < 24) {
        return `${hours}h`
    }
    const days = dayjs().diff(then, 'day')
    if (days < 30) {
        return `${days}d`
    }
    const months = dayjs().diff(then, 'month')
    if (months < 12) {
        return `${months}mo`
    }
    return `${dayjs().diff(then, 'year')}y`
}

function SourceBreakdown({
    sources,
    quietAfterDays,
}: {
    sources: DataFreshnessSourceApi[]
    quietAfterDays: number
}): JSX.Element | null {
    if (!sources.length) {
        return null
    }
    return (
        <div className="flex flex-col gap-0.5 mt-1">
            {sources.map((source) => {
                const isStale = dayjs().diff(dayjs(source.last_data_at), 'day') >= quietAfterDays
                return (
                    <div key={source.data_source} className="flex items-center justify-between gap-4">
                        <span>{DATA_SOURCE_LABELS[source.data_source] ?? source.data_source}</span>
                        <span className={cn('shrink-0', isStale && 'text-tertiary')}>
                            {dayjs(source.last_data_at).fromNow()}
                        </span>
                    </div>
                )
            })}
        </div>
    )
}

/**
 * How long ago this project last received data of any kind, on every row rather than only the
 * problem ones. The question being answered is "which of these similarly-named projects is the
 * live one", which is a comparison across the whole list, so every row has to carry a value.
 * `now` next to a column of `3mo` answers it without needing color or a badge.
 */
export function ProjectFreshnessIndicator({
    freshness,
    quietAfterDays,
    lookbackDays,
}: {
    freshness: DataFreshnessProjectApi | undefined
    quietAfterDays: number
    lookbackDays: number
}): JSX.Element | null {
    if (!freshness) {
        return null
    }

    let label: string
    let headline: string

    if (freshness.freshness === 'never') {
        label = 'Never'
        headline = 'This project has never received any data.'
    } else if (!freshness.last_data_at) {
        label = `${lookbackDays}d+`
        headline = `No data of any kind in the last ${lookbackDays} days.`
    } else {
        label = compactAge(freshness.last_data_at)
        headline =
            freshness.freshness === 'live'
                ? `Last received data ${dayjs(freshness.last_data_at).fromNow()}.`
                : `No data of any kind since ${dayjs(freshness.last_data_at).fromNow()}.`
    }

    return (
        <Tooltip
            placement="right"
            title={
                <div className="max-w-xs">
                    <span>{headline}</span>
                    <SourceBreakdown sources={freshness.sources} quietAfterDays={quietAfterDays} />
                </div>
            }
        >
            <span
                className={cn(
                    'text-xxs shrink-0 ml-1 whitespace-nowrap tabular-nums',
                    // The live row is the one being looked for, so it keeps normal contrast while
                    // the rest recede. With one live project among ten only that row reads at full
                    // strength; with ten live projects nothing is dimmed and nothing shouts.
                    freshness.freshness === 'live' ? 'text-secondary' : 'text-tertiary opacity-70'
                )}
            >
                {label}
            </span>
        </Tooltip>
    )
}
