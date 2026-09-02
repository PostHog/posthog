import { Noun } from '~/models/groupsModel'
import { DateRange } from '~/queries/schema/schema-general'

import {
    buildEnrichedUsageCharts,
    buildFlagCalledTotalVolumeChart,
    buildFlagCalledUniqueCallersChart,
    FlagUsageChart,
    FlagUsageQueryOptions,
} from './featureFlagUsageQueries'

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
        ['buildFlagCalledTotalVolumeChart', (): FlagUsageChart => buildFlagCalledTotalVolumeChart(personFlagOptions)],
        [
            'buildFlagCalledUniqueCallersChart',
            (): FlagUsageChart => buildFlagCalledUniqueCallersChart(personFlagOptions),
        ],
        ['buildEnrichedUsageCharts', (): FlagUsageChart => buildEnrichedUsageCharts(personFlagOptions)[0]],
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
            (options: FlagUsageQueryOptions): FlagUsageChart => buildFlagCalledTotalVolumeChart(options),
        ],
        [
            'buildFlagCalledUniqueCallersChart',
            (options: FlagUsageQueryOptions): FlagUsageChart => buildFlagCalledUniqueCallersChart(options),
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
