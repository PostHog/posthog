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

// Short forms for the row label, where a full product name would crowd out the project name.
const DATA_SOURCE_SHORT_LABELS: Record<DataSourceEnumApi, string> = {
    product_analytics: 'Analytics',
    session_replay: 'Replay',
    error_tracking: 'Errors',
    llm_analytics: 'LLM',
    surveys: 'Surveys',
    feature_flags: 'Flags',
    logs: 'Logs',
    apm: 'Tracing',
    destinations: 'Destinations',
    messaging: 'Messaging',
    data_warehouse: 'Warehouse',
}

function daysSince(timestamp: string): number {
    return dayjs().diff(dayjs(timestamp), 'day')
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

function describe(
    freshness: DataFreshnessProjectApi,
    quietAfterDays: number,
    lookbackDays: number
): { label: string; headline: string; isAlarming: boolean } {
    if (freshness.freshness === 'never') {
        return {
            label: 'No data yet',
            headline: 'This project has not received any data yet.',
            isAlarming: false,
        }
    }

    if (freshness.freshness === 'quiet') {
        if (!freshness.last_data_at) {
            return {
                label: `Quiet ${lookbackDays}d+`,
                headline: `No data of any kind has reached this project in the last ${lookbackDays} days.`,
                isAlarming: true,
            }
        }
        const days = daysSince(freshness.last_data_at)
        return {
            label: `Quiet ${days}d`,
            headline: `No data of any kind has reached this project in ${days} days.`,
            isAlarming: true,
        }
    }

    const quietSources = freshness.sources.filter((source) => daysSince(source.last_data_at) >= quietAfterDays)
    return {
        // Naming the one dead source is the whole point of this state, so it goes in the row
        // rather than hiding behind a hover. Beyond one, the count is all that fits.
        label:
            quietSources.length === 1
                ? `${DATA_SOURCE_SHORT_LABELS[quietSources[0].data_source] ?? quietSources[0].data_source} quiet`
                : `${quietSources.length} sources quiet`,
        headline: 'Data is still arriving, but some sources have gone quiet.',
        isAlarming: false,
    }
}

/**
 * Says something only when there is something to say: a project where everything is still
 * arriving renders nothing, so the switcher stays quiet until a project doesn't.
 *
 * Matches the "Pending invite" label in this same list rather than inventing a second visual
 * language for row status: one right-aligned text run, no icon, so every row lines up and
 * color is left to carry severity.
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

    const { label, headline, isAlarming } = describe(freshness, quietAfterDays, lookbackDays)

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
                    isAlarming ? 'text-warning' : 'text-tertiary'
                )}
            >
                {label}
            </span>
        </Tooltip>
    )
}
