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
 * Compact enough to sit in a menu row without crowding the project name. Only ever called for a
 * gap of at least `quiet_after_days`, so it starts at days. `mo` rather than `m`, which would
 * read as minutes.
 */
function compactAge(timestamp: string): string {
    const then = dayjs(timestamp)
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
 * A warning on projects that have stopped receiving data, and nothing at all on the ones that
 * haven't. The label says what the duration measures rather than leaving a bare `12d` for the
 * reader to interpret, because there is no column header in a menu to explain it.
 *
 * A project that has never received anything is stated plainly rather than warned about: a
 * project created a minute ago legitimately has no data, and amber on it would be wrong.
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
    if (!freshness || freshness.freshness === 'live') {
        return null
    }

    let label: string
    let headline: string

    if (freshness.freshness === 'never') {
        label = 'No data yet'
        headline = 'This project has never received any data.'
    } else if (!freshness.last_data_at) {
        label = `No data for ${lookbackDays}d+`
        headline = `No data of any kind has reached this project in over ${lookbackDays} days.`
    } else {
        label = `No data for ${compactAge(freshness.last_data_at)}`
        headline = `No data of any kind has reached this project since ${dayjs(freshness.last_data_at).fromNow()}.`
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
                    'text-xxs shrink-0 ml-1 whitespace-nowrap',
                    freshness.freshness === 'never' ? 'text-tertiary' : 'text-warning'
                )}
            >
                {label}
            </span>
        </Tooltip>
    )
}
