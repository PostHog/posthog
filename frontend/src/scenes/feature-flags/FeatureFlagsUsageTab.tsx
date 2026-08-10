import { useState } from 'react'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { Link } from 'lib/lemon-ui/Link'

import { Query } from '~/queries/Query/Query'
import { NodeKind } from '~/queries/schema/schema-general'
import { BaseMathType, ChartDisplayType } from '~/types'

const DEFAULT_DATE_FROM = '-7d'

// Only the top slice is charted: a project with hundreds of flags would otherwise render a
// breakdown legend nobody can read, and the long tail is what the Overview tab is for.
const BREAKDOWN_LIMIT = 10

/**
 * `$feature_flag_called` fires once per flag read, but a single `/flags` request can serve many
 * flags at once — so evaluation count and request count are different numbers. Grouping by
 * `$feature_flag_request_id` recovers that fan-out.
 *
 * A request that served exactly one flag was caused by that flag: remove the flag and the request
 * goes away. A request that served many is shared, and there is no non-arbitrary way to split it —
 * reading one more flag off an existing response costs nothing. Bucketing keeps those two cases
 * visibly separate instead of averaging them into a per-flag number that would imply the wrong
 * optimization.
 *
 * Locally evaluated reads issue no `/flags` request at all, so they carry no request id and drop
 * out via the `notEmpty` filter rather than needing a `locally_evaluated` predicate.
 */
const FLAGS_PER_REQUEST_QUERY = `
SELECT
    multiIf(
        flags_in_request = 1, '1 flag',
        flags_in_request <= 5, '2-5 flags',
        flags_in_request <= 20, '6-20 flags',
        '21+ flags'
    ) AS flags_served_per_request,
    count() AS flags_requests,
    sum(flags_in_request) AS flag_evaluations
FROM (
    SELECT
        properties.$feature_flag_request_id AS request_id,
        count() AS flags_in_request
    FROM events
    WHERE event = '$feature_flag_called'
      AND {filters}
      AND notEmpty(toString(properties.$feature_flag_request_id))
    GROUP BY request_id
)
GROUP BY flags_served_per_request
ORDER BY min(flags_in_request)
`

export function FeatureFlagsUsageTab(): JSX.Element {
    const [dateFrom, setDateFrom] = useState<string | null>(DEFAULT_DATE_FROM)
    const [dateTo, setDateTo] = useState<string | null>(null)

    return (
        <div className="deprecated-space-y-4">
            <LemonBanner type="info">
                Counts come from <code>$feature_flag_called</code> events, which are captured per flag read. Projects
                with flag-called deduplication enabled have repeat reads of the same flag and value collapsed within a
                short window, so treat these numbers as a lower bound on raw evaluations.
            </LemonBanner>

            <DateFilter
                dateFrom={dateFrom}
                dateTo={dateTo}
                onChange={(from, to) => {
                    setDateFrom(from)
                    setDateTo(to)
                }}
            />

            <div>
                <h3>Evaluations by flag</h3>
                <p className="text-secondary">
                    Which flags are read most often, across every project SDK. Top {BREAKDOWN_LIMIT} flags shown.
                </p>
                <Query
                    query={{
                        kind: NodeKind.InsightVizNode,
                        source: {
                            kind: NodeKind.TrendsQuery,
                            series: [
                                {
                                    kind: NodeKind.EventsNode,
                                    event: '$feature_flag_called',
                                    name: '$feature_flag_called',
                                    math: BaseMathType.TotalCount,
                                },
                            ],
                            breakdownFilter: {
                                breakdown: '$feature_flag',
                                breakdown_type: 'event',
                                breakdown_limit: BREAKDOWN_LIMIT,
                            },
                            dateRange: { date_from: dateFrom, date_to: dateTo },
                            interval: 'day',
                            trendsFilter: { display: ChartDisplayType.ActionsLineGraph },
                        },
                    }}
                />
            </div>

            <div>
                <h3>Flags served per /flags request</h3>
                <p className="text-secondary">
                    How many flag evaluations each <code>/flags</code> request produced. Requests serving a single flag
                    are attributable to that flag; requests serving many are shared across them, because reading an
                    extra flag off a response already fetched costs nothing. Locally evaluated reads make no{' '}
                    <code>/flags</code> request and are excluded.{' '}
                    <Link to="https://posthog.com/docs/feature-flags/local-evaluation">Local evaluation docs</Link>
                </p>
                <Query
                    query={{
                        kind: NodeKind.DataTableNode,
                        source: {
                            kind: NodeKind.HogQLQuery,
                            query: FLAGS_PER_REQUEST_QUERY,
                            filters: { dateRange: { date_from: dateFrom, date_to: dateTo } },
                        },
                        full: false,
                    }}
                />
            </div>
        </div>
    )
}
