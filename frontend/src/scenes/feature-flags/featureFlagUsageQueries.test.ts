import { dateMapping } from 'lib/utils/dateFilters'

import { Noun } from '~/models/groupsModel'
import { DataVisualizationNode, DateRange, InsightVizNode, TrendsQuery } from '~/queries/schema/schema-general'

import {
    buildEnrichedUsageCharts,
    buildFlagCalledTotalVolumeChart,
    buildFlagCalledUniqueCallersChart,
    buildFlagEvaluationsTotalVolumeChart,
    buildFlagEvaluationsUniqueCallersChart,
    clampToFlagEvaluationsRetention,
    FLAG_EVALUATIONS_RETENTION_DAYS,
    FLAG_EVALUATIONS_VOLUME_ROW_LIMIT,
    flagEvaluationsDateOptions,
    FlagUsageChart,
    FlagUsageQueryOptions,
} from './featureFlagUsageQueries'

type TrendsUsageChart = FlagUsageChart<InsightVizNode<TrendsQuery>>

const flagEvaluationsBuilders: [string, (options: FlagUsageQueryOptions) => FlagUsageChart<DataVisualizationNode>][] = [
    ['buildFlagEvaluationsTotalVolumeChart', buildFlagEvaluationsTotalVolumeChart],
    ['buildFlagEvaluationsUniqueCallersChart', buildFlagEvaluationsUniqueCallersChart],
]

const dateRange: DateRange = { date_from: '-30d', date_to: null }
const userNoun: Noun = { singular: 'user', plural: 'users' }

const personFlagOptions: FlagUsageQueryOptions = {
    flagKey: 'alpha-feature',
    aggregationGroupTypeIndex: null,
    callerNoun: userNoun,
    dateRange,
}

const groupFlagOptions: FlagUsageQueryOptions = {
    flagKey: 'group-feature',
    aggregationGroupTypeIndex: 0,
    callerNoun: { singular: 'organization', plural: 'organizations' },
    dateRange,
}

describe('featureFlagUsageQueries', () => {
    it.each([
        ['buildFlagCalledTotalVolumeChart', (): TrendsUsageChart => buildFlagCalledTotalVolumeChart(personFlagOptions)],
        [
            'buildFlagCalledUniqueCallersChart',
            (): TrendsUsageChart => buildFlagCalledUniqueCallersChart(personFlagOptions),
        ],
        ['buildEnrichedUsageCharts', (): TrendsUsageChart => buildEnrichedUsageCharts(personFlagOptions)[0]],
    ])('%s builds an unsaved TrendsQuery with the shared envelope', (_name, build) => {
        const { query } = build()

        expect(query.kind).toEqual('InsightVizNode')
        expect(query.source.kind).toEqual('TrendsQuery')
        expect(query.source.version).not.toBeUndefined()
        expect(query.source.filterTestAccounts).toBe(false)
        expect(query.source.dateRange).toEqual(dateRange)
    })

    it.each([
        ['-30d', 'day'],
        ['-24h', 'hour'],
        ['-180d', 'month'],
    ])('derives the interval for %s from the date range', (date_from, expected) => {
        const { query } = buildFlagCalledTotalVolumeChart({
            ...personFlagOptions,
            dateRange: { date_from, date_to: null },
        })

        expect(query.source.interval).toEqual(expected)
    })

    it('buildFlagCalledTotalVolumeChart targets $feature_flag_called with no math and the feature-flag-response breakdown', () => {
        const { query } = buildFlagCalledTotalVolumeChart(personFlagOptions)

        expect(query.source.series).toMatchObject([
            { kind: 'EventsNode', event: '$feature_flag_called', name: '$feature_flag_called' },
        ])
        expect(query.source.series[0]).not.toHaveProperty('math')
        expect(query.source.breakdownFilter).toEqual({
            breakdown: '$feature_flag_response',
            breakdown_type: 'event',
        })
        expect(query.source.trendsFilter).toMatchObject({
            display: 'ActionsLineGraph',
            aggregationAxisFormat: 'numeric',
        })
    })

    it.each([
        [
            'buildFlagCalledTotalVolumeChart',
            (options: FlagUsageQueryOptions): TrendsUsageChart => buildFlagCalledTotalVolumeChart(options),
        ],
        [
            'buildFlagCalledUniqueCallersChart',
            (options: FlagUsageQueryOptions): TrendsUsageChart => buildFlagCalledUniqueCallersChart(options),
        ],
    ])('%s filters on $feature_flag, adding a $group_N is_set filter only for group flags', (_name, build) => {
        expect(build(personFlagOptions).query.source.properties).toEqual([
            { key: '$feature_flag', type: 'event', operator: 'exact', value: 'alpha-feature' },
        ])
        expect(build(groupFlagOptions).query.source.properties).toEqual([
            { key: '$feature_flag', type: 'event', operator: 'exact', value: 'group-feature' },
            { key: '$group_0', type: 'event', operator: 'is_set', value: 'is_set' },
        ])
    })

    it('buildFlagCalledUniqueCallersChart uses dau math and an ActionsTable display for a person flag', () => {
        const { title, query } = buildFlagCalledUniqueCallersChart(personFlagOptions)

        expect(title).toEqual('Feature flag calls made by unique users per variant')
        expect(query.source.series).toMatchObject([
            { kind: 'EventsNode', event: '$feature_flag_called', name: '$feature_flag_called', math: 'dau' },
        ])
        expect(query.source.trendsFilter).toMatchObject({ display: 'ActionsTable' })
    })

    it('buildFlagCalledUniqueCallersChart uses unique_group math and the group noun for a group flag', () => {
        const { title, query } = buildFlagCalledUniqueCallersChart(groupFlagOptions)

        expect(title).toEqual('Feature flag calls made by unique organizations per variant')
        expect(query.source.series).toMatchObject([
            {
                kind: 'EventsNode',
                event: '$feature_flag_called',
                name: '$feature_flag_called',
                math: 'unique_group',
                math_group_type_index: 0,
            },
        ])
    })

    it('buildEnrichedUsageCharts builds total and unique-user series for feature view and interaction events', () => {
        const [featureView, featureInteraction] = buildEnrichedUsageCharts(personFlagOptions)

        expect(featureView.query.source.series).toMatchObject([
            { kind: 'EventsNode', event: '$feature_view', name: 'Feature view - Total' },
            { kind: 'EventsNode', event: '$feature_view', name: 'Feature view - Unique users', math: 'dau' },
        ])
        expect(featureInteraction.query.source.series).toMatchObject([
            { kind: 'EventsNode', event: '$feature_interaction', name: 'Feature interaction - Total' },
            {
                kind: 'EventsNode',
                event: '$feature_interaction',
                name: 'Feature interaction - Unique users',
                math: 'dau',
            },
        ])
    })

    it.each(flagEvaluationsBuilders)('%s reads flag_evaluations over the tab date range', (_name, build) => {
        const { query } = build(personFlagOptions)

        expect(query.kind).toEqual('DataVisualizationNode')
        expect(query.source.kind).toEqual('HogQLQuery')
        expect(query.source.query).toContain('FROM posthog.flag_evaluations')
        expect(query.source.query).toContain("flag_key = 'alpha-feature'")
        // Without the date filter the query scans the whole retention window whatever range the
        // tab shows.
        expect(query.source.query).toContain('{filters(timestamp AS timestamp)}')
        expect(query.source.filters).toEqual({ dateRange })
        // HogQLQueryRunner compiles every placeholder in `values` while it parses, and
        // `{filters(...)}` is not compilable, so carrying both fails the query at run time. The
        // unit tests read the query string alone, so only this assertion catches a re-added value.
        expect(query.source.values).toBeUndefined()
        // The backend cannot infer a product for this table, and an untagged ClickHouse query
        // raises under DEBUG.
        expect(query.source.tags).toEqual({ productKey: 'feature_flags' })
    })

    it.each(flagEvaluationsBuilders)('%s escapes a quote in the flag key', (_name, build) => {
        // The flag key reaches the SQL as a literal, so an unescaped quote closes the string and
        // the rest of the key parses as HogQL.
        const { query } = build({ ...personFlagOptions, flagKey: "o'brien-flag" })

        expect(query.source.query).toContain("flag_key = 'o\\'brien-flag'")
    })

    it('buildFlagEvaluationsTotalVolumeChart breaks the line graph down by response over the date range interval', () => {
        const { query } = buildFlagEvaluationsTotalVolumeChart({
            ...personFlagOptions,
            dateRange: { date_from: '-24h', date_to: null },
        })

        expect(query.display).toEqual('ActionsLineGraph')
        expect(query.source.query).toContain("dateTrunc('hour', timestamp) AS period")
        expect(query.chartSettings).toEqual({
            xAxis: { column: 'period' },
            yAxis: [{ column: 'total' }],
            seriesBreakdownColumn: 'variant',
            showNullsAsZero: true,
        })
    })

    it('buildFlagEvaluationsTotalVolumeChart limits past the rows the widest supported window returns', () => {
        // HogQL falls back to 100 rows without a LIMIT, and 90 days across two variants already
        // passes that, so the newest periods would drop off the end of a period-ascending chart.
        const { query } = buildFlagEvaluationsTotalVolumeChart({
            ...personFlagOptions,
            dateRange: { date_from: `-${FLAG_EVALUATIONS_RETENTION_DAYS}d`, date_to: null },
        })

        expect(query.source.query).toContain(`LIMIT ${FLAG_EVALUATIONS_VOLUME_ROW_LIMIT}`)
        expect(FLAG_EVALUATIONS_VOLUME_ROW_LIMIT).toBeGreaterThan(FLAG_EVALUATIONS_RETENTION_DAYS * 2)
    })

    it.each([
        ['-24h', 'hour'],
        ['-30d', 'day'],
    ])('buildFlagEvaluationsTotalVolumeChart fills the quiet %s periods of every variant', (date_from, interval) => {
        // GROUP BY skips a period with no evaluations, which would read as a gap in the line
        // rather than the drop to zero it is. The fill step has to match the dateTrunc unit.
        const { query } = buildFlagEvaluationsTotalVolumeChart({
            ...personFlagOptions,
            dateRange: { date_from, date_to: null },
        })

        expect(query.source.query).toContain(`ORDER BY variant, period WITH FILL STEP INTERVAL 1 ${interval}`)
        // The fill reorders rows by variant, so the outer query has to put them back in time order.
        expect(
            query.source.query.trimEnd().endsWith(`ORDER BY period\nLIMIT ${FLAG_EVALUATIONS_VOLUME_ROW_LIMIT}`)
        ).toBe(true)
    })

    it.each([
        ['person flag', personFlagOptions, 'uniq(person_id)', false],
        ['group flag', groupFlagOptions, 'uniq(`$group_0`)', true],
    ])(
        'buildFlagEvaluationsUniqueCallersChart counts the callers of a %s',
        (_name, options, expectedAggregation, expectsGroupFilter) => {
            const { query } = buildFlagEvaluationsUniqueCallersChart(options)

            expect(query.source.query).toContain(expectedAggregation)
            expect(query.source.query.includes("`$group_0` != ''")).toEqual(expectsGroupFilter)
        }
    )

    it.each([
        [
            'a range inside the window is left alone',
            { date_from: '-30d', date_to: null },
            { date_from: '-30d', date_to: null },
        ],
        ['the window itself is left alone', { date_from: '-90d', date_to: null }, { date_from: '-90d', date_to: null }],
        ['a longer range is pulled back', { date_from: '-180d', date_to: null }, { date_from: '-90d', date_to: null }],
        ['all time is pulled back', { date_from: 'all', date_to: null }, { date_from: '-90d', date_to: null }],
        ['a missing start is pulled back', { date_from: null, date_to: null }, { date_from: '-90d', date_to: null }],
        [
            'a range that ends before the window runs to now instead of backwards',
            { date_from: '-200d', date_to: '-150d' },
            { date_from: '-90d', date_to: null },
        ],
        [
            'an end inside the window is kept',
            { date_from: '-200d', date_to: '-10d' },
            { date_from: '-90d', date_to: '-10d' },
        ],
    ])('clampToFlagEvaluationsRetention: %s', (_name, dateRange, expected) => {
        expect(clampToFlagEvaluationsRetention(dateRange)).toEqual(expected)
    })

    it('flagEvaluationsDateOptions offers no preset older than the retention window', () => {
        const keys = flagEvaluationsDateOptions().map((option) => option.key)

        expect(keys).toContain('Last 90 days')
        expect(keys).toContain('Last 30 days')
        expect(keys).not.toContain('Last 180 days')
        expect(keys).not.toContain('All time')
        // The custom entry carries no range of its own, so it must survive the filter.
        expect(keys).toContain(dateMapping[0].key)
    })

    it('buildEnrichedUsageCharts filters on the bare feature_flag property key with no breakdown', () => {
        // A wrong property key here silently produces an empty chart, so pin the exact key.
        for (const chart of buildEnrichedUsageCharts(personFlagOptions)) {
            expect(chart.query.source.properties).toEqual([
                { key: 'feature_flag', type: 'event', operator: 'exact', value: 'alpha-feature' },
            ])
            expect(chart.query.source.breakdownFilter).toBeUndefined()
        }
    })
})
