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
    MarketingAnalyticsRetentionRow,
} from '~/queries/schema/schema-general'

import { BREAKDOWN_LABELS, displayBreakdownValue, isFoldedBreakdownValue } from '../../logic/marketingBreakdown'
import {
    MARKETING_ANALYTICS_RETENTION_COLLECTION_ID,
    marketingRetentionLogic,
} from '../../logic/marketingRetentionLogic'
import { RetentionSummaryTable } from './RetentionSummaryTable'

const EXPANDED_BY_DEFAULT = 3

/** Same values as PostHog's retention table, so a rate reads as the same shade on both. */
const CELL_COLOR = '#1d4aff'
const CELL_COLOR_FLOOR = 0.1
/** Past this the background is dark enough that the theme's text fails WCAG AA. */
const CELL_TEXT_LIGHT_THRESHOLD = 0.4

/** In the team's timezone: a UTC cohort read from New York would be labelled with the previous day. */
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

// Stable, because `useAttachedLogic` only detaches when the scene unmounts. An incrementing key leaves
// a fresh dataNodeLogic attached on every visit to the tab, and the filter bar's ReloadAll then re-runs
// each earlier visit's stale query on top of the live one.
const RETENTION_DATA_NODE_KEY = 'MarketingRetention'

export function RetentionCohortTable({
    query,
    attachTo,
}: {
    query: MarketingAnalyticsRetentionQuery
    attachTo?: LogicWrapper | BuiltLogic
}): JSX.Element {
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

    const caveats: string[] = []
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
                            style={{
                                backgroundColor: gradateColor(CELL_COLOR, cell.rate ?? 0, CELL_COLOR_FLOOR),
                                color: (cell.rate ?? 0) > CELL_TEXT_LIGHT_THRESHOLD ? '#fff' : 'var(--text-3000)',
                            }}
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
    // "Other" is a sum of the tail, so ranking it by size floats it above real channels.
    const breakdownValues = [...byBreakdown.keys()].sort((a, b) => {
        if (isFoldedBreakdownValue(a) !== isFoldedBreakdownValue(b)) {
            return isFoldedBreakdownValue(a) ? 1 : -1
        }
        return totalAcquired(byBreakdown.get(b)) - totalAcquired(byBreakdown.get(a))
    })

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
        <div className="flex flex-col gap-4">
            {caveats.length > 0 && <div className="text-secondary text-xs">{caveats.join(' ')}</div>}
            <RetentionSummaryTable rows={rows} labels={labels} dimensionLabel={dimensionLabel} />
            <div>
                <div className="text-muted mb-1 text-xs font-semibold uppercase">
                    All {dimensionLabel.toLowerCase()}s
                </div>
                <LemonTable columns={columns} dataSource={baselineRows(rows)} size="small" firstColumnSticky />
            </div>
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

/**
 * Rates are recomputed from the summed counts, because averaging per-channel rates would weight a
 * channel with ten people the same as one with ten thousand.
 */
export function baselineRows(rows: MarketingAnalyticsRetentionRow[]): MarketingAnalyticsRetentionRow[] {
    const byCohort = new Map<number, MarketingAnalyticsRetentionRow>()
    for (const row of rows) {
        const merged = byCohort.get(row.cohortIndex)
        if (!merged) {
            byCohort.set(row.cohortIndex, {
                ...row,
                breakdownValue: '',
                values: row.values.map((cell) => ({ ...cell })),
            })
            continue
        }
        merged.cohortSize += row.cohortSize
        row.values.forEach((cell, index) => {
            const into = merged.values[index]
            if (into) {
                into.count += cell.count
            }
        })
    }
    return [...byCohort.values()]
        .sort((a, b) => a.cohortIndex - b.cohortIndex)
        .map((row) => ({
            ...row,
            values: row.values.map((cell) => ({
                ...cell,
                rate: row.cohortSize ? cell.count / row.cohortSize : null,
            })),
        }))
}
