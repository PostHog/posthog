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

function daysSince(timestamp: string): number {
    return dayjs().diff(dayjs(timestamp), 'day')
}

function QuietDot({ className }: { className?: string }): JSX.Element {
    return <span className={cn('size-1.5 rounded-full bg-warning shrink-0', className)} />
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
                const isQuiet = daysSince(source.last_data_at) >= quietAfterDays
                return (
                    <div key={source.data_source} className="flex items-center justify-between gap-4">
                        <span>{DATA_SOURCE_LABELS[source.data_source] ?? source.data_source}</span>
                        <span className={cn('shrink-0', isQuiet ? 'text-warning' : 'text-tertiary')}>
                            {dayjs(source.last_data_at).fromNow()}
                        </span>
                    </div>
                )
            })}
        </div>
    )
}

/**
 * Says something only when there is something to say: a project where everything is still
 * arriving renders nothing, so the switcher stays quiet until a project doesn't.
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

    let label: string | null = null
    let headline: string

    if (freshness.freshness === 'never') {
        headline = 'This project has not received any data yet.'
        label = 'No data yet'
    } else if (freshness.freshness === 'quiet') {
        if (freshness.last_data_at) {
            const days = daysSince(freshness.last_data_at)
            headline = `No data of any kind has reached this project in ${days} days.`
            label = `Quiet ${days}d`
        } else {
            headline = `No data of any kind has reached this project in the last ${lookbackDays} days.`
            label = 'No recent data'
        }
    } else {
        headline = 'Data is still arriving, but some sources have gone quiet.'
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
            <span className="ml-auto flex items-center gap-1 shrink-0 text-xxs text-tertiary">
                {freshness.freshness !== 'never' && <QuietDot />}
                {label}
            </span>
        </Tooltip>
    )
}
