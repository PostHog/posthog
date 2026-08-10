import { useState } from 'react'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { Link } from 'lib/lemon-ui/Link'
import { dateMapping } from 'lib/utils/dateFilters'

import { Query } from '~/queries/Query/Query'
import { NodeKind } from '~/queries/schema/schema-general'
import {
    AnyPropertyFilter,
    BaseMathType,
    ChartDisplayType,
    HogQLMathType,
    IntervalType,
    PropertyFilterType,
    PropertyOperator,
} from '~/types'

const DEFAULT_DATE_FROM = '-7d'

// A project with hundreds of flags would otherwise render a breakdown legend nobody can read.
const BREAKDOWN_LIMIT = 10

// Locally evaluated reads never call /flags, so they carry no request id. Excluding them keeps the
// request counts honest.
const HAS_REQUEST_ID: AnyPropertyFilter[] = [
    {
        key: '$feature_flag_request_id',
        type: PropertyFilterType.Event,
        operator: PropertyOperator.IsSet,
        value: 'is_set',
    },
]

// One /flags request can serve many flags, so counting events would report evaluations rather than
// requests. Counting distinct request ids reports requests.
const REQUESTS_PER_FLAG = 'uniq(properties.$feature_flag_request_id)'

// Each preset carries the granularity it reads best at, so a short range doesn't collapse to a
// single daily point. Rolling ranges ("Last 3 weeks") match no preset and fall back to days.
function intervalForRange(dateFrom: string | null): IntervalType {
    return dateMapping.find((option) => option.values[0] === dateFrom)?.defaultInterval ?? 'day'
}

export function FeatureFlagsUsageTab(): JSX.Element {
    const [dateFrom, setDateFrom] = useState<string | null>(DEFAULT_DATE_FROM)
    const [dateTo, setDateTo] = useState<string | null>(null)

    const interval = intervalForRange(dateFrom)

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
                            interval,
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
                    query={{
                        kind: NodeKind.InsightVizNode,
                        source: {
                            kind: NodeKind.TrendsQuery,
                            series: [
                                {
                                    kind: NodeKind.EventsNode,
                                    event: '$feature_flag_called',
                                    name: '$feature_flag_called',
                                    math: HogQLMathType.HogQL,
                                    math_hogql: REQUESTS_PER_FLAG,
                                    properties: HAS_REQUEST_ID,
                                },
                            ],
                            breakdownFilter: {
                                breakdown: '$feature_flag',
                                breakdown_type: 'event',
                                breakdown_limit: BREAKDOWN_LIMIT,
                            },
                            dateRange: { date_from: dateFrom, date_to: dateTo },
                            interval,
                            trendsFilter: { display: ChartDisplayType.ActionsLineGraph },
                        },
                    }}
                />
            </div>
        </div>
    )
}
