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
    flagEvaluationsDateOptions,
    FlagUsageChart,
    FlagUsageQueryOptions,
} from './featureFlagUsageQueries'

type TrendsUsageChart = FlagUsageChart<InsightVizNode<TrendsQuery>>

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

    it.each([
        [
            'buildFlagEvaluationsTotalVolumeChart',
            (options: FlagUsageQueryOptions): FlagUsageChart<DataVisualizationNode> =>
                buildFlagEvaluationsTotalVolumeChart(options),
        ],
        [
            'buildFlagEvaluationsUniqueCallersChart',
            (options: FlagUsageQueryOptions): FlagUsageChart<DataVisualizationNode> =>
                buildFlagEvaluationsUniqueCallersChart(options),
        ],
    ])('%s reads flag_evaluations with the flag key and date range bound as parameters', (_name, build) => {
        const { query } = build(personFlagOptions)

        expect(query.kind).toEqual('DataVisualizationNode')
        expect(query.source.kind).toEqual('HogQLQuery')
        expect(query.source.query).toContain('FROM posthog.flag_evaluations')
        // An inlined flag key would be a HogQL injection, and a missing date filter would scan
        // the whole retention window whatever range the tab shows.
        expect(query.source.query).toContain('flag_key = {flag_key}')
        expect(query.source.query).toContain('{filters(timestamp AS timestamp)}')
        expect(query.source.values?.flag_key).toEqual('alpha-feature')
        expect(query.source.filters).toEqual({ dateRange })
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
        })
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
