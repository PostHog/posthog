import { useValues } from 'kea'

import { dayjs } from 'lib/dayjs'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { cn } from 'lib/utils/css-classes'

import type {
    DataFreshnessSourceApi,
    DataSourceEnumApi,
} from 'products/platform_features/frontend/generated/api.schemas'

import { projectDataFreshnessLogic } from './projectDataFreshnessLogic'

const DATA_SOURCE_LABELS: Record<DataSourceEnumApi, string> = {
    product_analytics: 'Product analytics',
    session_replay: 'Session replay',
    error_tracking: 'Error tracking',
    llm_analytics: 'LLM analytics',
    surveys: 'Surveys',
    feature_flags: 'Feature flags',
    logs: 'Logs',
    tracing: 'Tracing',
    pipeline_destinations: 'Destinations',
    workflows: 'Workflows',
    data_warehouse: 'Data warehouse',
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
                        <span>{DATA_SOURCE_LABELS[source.data_source]}</span>
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
export function ProjectFreshnessIndicator({ teamId }: { teamId: number }): JSX.Element | null {
    const { dataFreshness, freshnessByTeamId } = useValues(projectDataFreshnessLogic)

    const freshness = freshnessByTeamId[teamId]
    if (!dataFreshness || !freshness || freshness.freshness === 'live') {
        return null
    }

    let label: string
    let headline: string

    if (freshness.freshness === 'never') {
        label = 'No data yet'
        headline = 'This project has never received any data.'
    } else if (!freshness.last_data_at) {
        // Every probe is bounded to the lookback window, so this is as far back as we can see.
        label = `No data for ${dataFreshness.lookback_days}d+`
        headline = `No data of any kind has reached this project in over ${dataFreshness.lookback_days} days.`
    } else {
        label = `No data for ${dayjs().diff(dayjs(freshness.last_data_at), 'day')}d`
        headline = `No data of any kind has reached this project since ${dayjs(freshness.last_data_at).fromNow()}.`
    }

    return (
        <Tooltip
            placement="right"
            title={
                <div className="max-w-xs">
                    <span>{headline}</span>
                    <SourceBreakdown sources={freshness.sources} quietAfterDays={dataFreshness.quiet_after_days} />
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
