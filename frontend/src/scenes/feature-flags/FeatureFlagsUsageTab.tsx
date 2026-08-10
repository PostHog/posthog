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
 * One `/flags` request can serve many flags, so counting `$feature_flag_called` rows would report
 * evaluations rather than requests. `uniq($feature_flag_request_id)` collapses each request to one
 * per flag per day.
 *
 * A request shared across flags is counted once for every flag it returned, so the series do not
 * sum to the project's request total. Locally evaluated reads issue no request and carry no request
 * id, so `notEmpty` drops them without needing a `locally_evaluated` predicate.
 */
const FLAG_REQUESTS_BY_FLAG_QUERY = `
WITH top_flags AS (
    SELECT properties.$feature_flag AS flag
    FROM events
    WHERE event = '$feature_flag_called'
      AND {filters}
      AND notEmpty(toString(properties.$feature_flag_request_id))
    GROUP BY flag
    ORDER BY uniq(properties.$feature_flag_request_id) DESC
    LIMIT ${BREAKDOWN_LIMIT}
)
SELECT
    toStartOfDay(timestamp) AS period,
    properties.$feature_flag AS flag,
    uniq(properties.$feature_flag_request_id) AS flags_requests
FROM events
WHERE event = '$feature_flag_called'
  AND {filters}
  AND notEmpty(toString(properties.$feature_flag_request_id))
  AND properties.$feature_flag IN (SELECT flag FROM top_flags)
GROUP BY period, flag
ORDER BY period, flags_requests DESC
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
                <h3>Requests by flag</h3>
                <p className="text-secondary">
                    How many <code>/flags</code> requests included each flag. One request can serve several flags, and
                    it counts once for each flag it returned, so the series do not add up to your total request count.
                    Locally evaluated reads make no <code>/flags</code> request, so they are not counted here. Top{' '}
                    {BREAKDOWN_LIMIT} flags shown.{' '}
                    <Link to="https://posthog.com/docs/feature-flags/local-evaluation">Local evaluation docs</Link>
                </p>
                <Query
                    uniqueKey="feature-flags-usage-requests-by-flag"
                    query={{
                        kind: NodeKind.DataVisualizationNode,
                        source: {
                            kind: NodeKind.HogQLQuery,
                            query: FLAG_REQUESTS_BY_FLAG_QUERY,
                            filters: { dateRange: { date_from: dateFrom, date_to: dateTo } },
                        },
                        display: ChartDisplayType.ActionsLineGraph,
                        chartSettings: {
                            xAxis: { column: 'period' },
                            yAxis: [{ column: 'flags_requests' }],
                            seriesBreakdownColumn: 'flag',
                            showLegend: true,
                        },
                    }}
                />
            </div>
        </div>
    )
}
