import { BuiltLogic, LogicWrapper, useActions, useValues } from 'kea'

import { LemonCollapse, LemonTable, LemonTableColumn, Tooltip } from '@posthog/lemon-ui'

import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { gradateColor } from 'lib/utils/colors'
import { parseDateInTimezone } from 'lib/utils/datetime'
import { humanFriendlyNumber, percentage } from 'lib/utils/numbers'
import { InsightErrorState } from 'scenes/insights/EmptyStates'
import { teamLogic } from 'scenes/teamLogic'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import {
    MarketingAnalyticsRetentionInterval,
    MarketingAnalyticsRetentionQuery,
    MarketingAnalyticsRetentionQueryResponse,
    MarketingAnalyticsRetentionReturningEvent,
    MarketingAnalyticsRetentionRow,
} from '~/queries/schema/schema-general'

import { BREAKDOWN_LABELS, displayBreakdownValue, isFoldedBreakdownValue } from '../../logic/marketingBreakdown'
import {
    MARKETING_ANALYTICS_RETENTION_COLLECTION_ID,
    marketingRetentionLogic,
} from '../../logic/marketingRetentionLogic'

/** Breakdown values expanded on arrival. The rest collapse, so a wide breakdown stays scannable. */
const EXPANDED_BY_DEFAULT = 3

/** Matches PostHog's retention table: the darkest cell is full retention, and 0% still reads as a cell. */
const CELL_COLOR = '#1d4aff'
const CELL_COLOR_FLOOR = 0.1

/** Read in the team's timezone, not the browser's: a UTC cohort viewed from New York would otherwise
 *  be labelled with the previous day. */
const cohortLabel = (isoDate: string, interval: MarketingAnalyticsRetentionInterval, timezone: string): string => {
    const date = parseDateInTimezone(isoDate, timezone)
    switch (interval) {
        case MarketingAnalyticsRetentionInterval.Month:
            return date.format('MMM YYYY')
        case MarketingAnalyticsRetentionInterval.Week:
            return `${date.format('MMM D')} to ${date.add(6, 'day').format('MMM D')}`
        default:
            return date.format('ddd, MMM D')
    }
}

// One retention table renders at a time, so a single stable key is enough. An incrementing key
// would leave a fresh dataNodeLogic attached to the scene on every visit to the tab, since
// useAttachedLogic only detaches when the scene unmounts. The filter bar's ReloadAll would then
// re-run each earlier visit's stale query on top of the live one.
const RETENTION_DATA_NODE_KEY = 'MarketingRetention'

export function RetentionCohortTable({
    query,
    attachTo,
}: {
    query: MarketingAnalyticsRetentionQuery
    attachTo?: LogicWrapper | BuiltLogic
}): JSX.Element {
    // Registered under the tab's shared collection so the filter bar's ReloadAll reaches this query.
    const logic = dataNodeLogic({
        query,
        key: RETENTION_DATA_NODE_KEY,
        dataNodeCollectionId: MARKETING_ANALYTICS_RETENTION_COLLECTION_ID,
    })
    const { response, responseLoading, responseError } = useValues(logic)
    const { loadData } = useActions(logic)
    const { breakdownBy } = useValues(marketingRetentionLogic)
    const { timezone } = useValues(teamLogic)
    useAttachedLogic(logic, attachTo)

    const retentionResponse = response as MarketingAnalyticsRetentionQueryResponse | undefined
    const rows = retentionResponse?.results ?? []
    const labels = retentionResponse?.labels ?? []
    const interval = retentionResponse?.interval ?? MarketingAnalyticsRetentionInterval.Week
    const dimensionLabel = BREAKDOWN_LABELS[breakdownBy]

    // Both caps change what the table covers, so neither can stay silent: without this the tab shows a
    // narrower range than the date filter says, and an "Other" row of unknown size.
    const caveats: string[] = []
    // Under a goal the columns read as a retention curve but aren't one, and for a goal someone can
    // only complete once they are closer to a breakdown of when each person converted.
    if (retentionResponse?.returningEvent === MarketingAnalyticsRetentionReturningEvent.ConversionGoal) {
        caveats.push(
            `Each column counts people from the cohort who ${
                retentionResponse.conversionGoalName
                    ? `completed "${retentionResponse.conversionGoalName}"`
                    : 'converted'
            } in that period, not people who visited again. For a goal someone can only complete once, like a signup, each person appears in a single column.`
        )
    }
    if (retentionResponse?.truncatedCohorts) {
        caveats.push(
            `The ${humanFriendlyNumber(retentionResponse.truncatedCohorts)} earliest periods in your date range aren't included. Narrow the range, or group by a longer period, to see them.`
        )
    }
    if (retentionResponse?.otherBreakdownCount) {
        caveats.push(
            `"Other" groups the smallest ${humanFriendlyNumber(retentionResponse.otherBreakdownCount)} values.`
        )
    }

    if (responseError) {
        return <InsightErrorState query={query} onRetry={loadData} />
    }

    const columns: LemonTableColumn<MarketingAnalyticsRetentionRow, any>[] = [
        {
            title: 'Cohort',
            dataIndex: 'cohortDate',
            render: (_, row) => cohortLabel(row.cohortDate, interval, timezone),
        },
        {
            title: 'Acquired',
            dataIndex: 'cohortSize',
            align: 'right',
            render: (_, row) => humanFriendlyNumber(row.cohortSize),
        },
        ...labels.map((label, index) => ({
            title: label,
            key: label,
            align: 'center' as const,
            render: (_: any, row: MarketingAnalyticsRetentionRow) => {
                const cell = row.values[index]
                if (!cell) {
                    return null
                }
                if (!cell.complete) {
                    // A period that hasn't fully elapsed. Rendering its 0% like any other cell reads as
                    // churn rather than as a week that hasn't happened yet.
                    return (
                        <Tooltip title="This period hasn't finished yet, so there's nothing to measure.">
                            <span className="text-muted">–</span>
                        </Tooltip>
                    )
                }
                return (
                    <Tooltip title={`${humanFriendlyNumber(cell.count)} of ${humanFriendlyNumber(row.cohortSize)}`}>
                        <div
                            className="rounded px-2 py-1"
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{ backgroundColor: gradateColor(CELL_COLOR, cell.rate ?? 0, CELL_COLOR_FLOOR) }}
                        >
                            {cell.rate === null ? '–' : percentage(cell.rate, 1)}
                        </div>
                    </Tooltip>
                )
            },
        })),
    ]

    const byBreakdown = new Map<string, MarketingAnalyticsRetentionRow[]>()
    for (const row of rows) {
        byBreakdown.set(row.breakdownValue, [...(byBreakdown.get(row.breakdownValue) ?? []), row])
    }
    // "Other" is a sum of the tail, so ranking it by size can float it above every real channel and
    // spend one of the expanded-by-default slots on a row nobody can act on. Pinned last instead.
    const breakdownValues = [...byBreakdown.keys()].sort((a, b) => {
        if (isFoldedBreakdownValue(a) !== isFoldedBreakdownValue(b)) {
            return isFoldedBreakdownValue(a) ? 1 : -1
        }
        return totalAcquired(byBreakdown.get(b)) - totalAcquired(byBreakdown.get(a))
    })

    // Loading, empty and populated are three different screens. Falling through to the collapse while
    // the query is in flight renders an empty bordered box with no sign anything is happening.
    if (responseLoading || !breakdownValues.length) {
        return (
            <LemonTable
                columns={columns}
                dataSource={[]}
                loading={responseLoading}
                emptyState='No new users arrived in this period. Widen the date range, or turn off "Only new users" to include people who were already here.'
            />
        )
    }

    return (
        <div className="flex flex-col gap-2">
            {caveats.length > 0 && <div className="text-secondary text-xs">{caveats.join(' ')}</div>}
            <LemonCollapse
                multiple
                defaultActiveKeys={breakdownValues.slice(0, EXPANDED_BY_DEFAULT)}
                panels={breakdownValues.map((value) => ({
                    key: value,
                    header: (
                        <div className="flex items-center gap-2">
                            <span className="font-semibold">{displayBreakdownValue(value, dimensionLabel)}</span>
                            <span className="text-secondary text-xs">
                                {humanFriendlyNumber(totalAcquired(byBreakdown.get(value)))} acquired
                            </span>
                        </div>
                    ),
                    content: (
                        <LemonTable
                            columns={columns}
                            dataSource={byBreakdown.get(value) ?? []}
                            loading={responseLoading}
                            size="small"
                            firstColumnSticky
                        />
                    ),
                }))}
            />
        </div>
    )
}

const totalAcquired = (rows: MarketingAnalyticsRetentionRow[] | undefined): number =>
    (rows ?? []).reduce((total, row) => total + row.cohortSize, 0)
