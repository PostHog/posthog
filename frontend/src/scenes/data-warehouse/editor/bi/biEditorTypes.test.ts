import { NodeKind } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import {
    BIConfig,
    BIEditorView,
    BIField,
    buildBIQuery,
    createDefaultDateFilter,
    defaultAggregationForField,
    getBIDataSourceKey,
    getBIFieldId,
    getBISortOptions,
    isBIFieldCompatible,
    parseBIEditorState,
} from './biEditorTypes'

const eventField: BIField = {
    id: 'warehouse:events:event',
    name: 'event',
    expression: 'event',
    type: 'string',
    source: { table: 'events' },
}

const revenueField: BIField = {
    id: 'warehouse:events:properties.revenue',
    name: 'revenue',
    expression: 'properties.revenue',
    type: 'float',
    source: { table: 'events' },
}

const timestampField: BIField = {
    id: 'warehouse:events:timestamp',
    name: 'timestamp',
    expression: 'timestamp',
    type: 'datetime',
    source: { table: 'events' },
}

const browserField: BIField = {
    id: 'warehouse:events:properties.$browser',
    name: 'browser',
    expression: 'properties.$browser',
    type: 'string',
    source: { table: 'events' },
}

const countryField: BIField = {
    id: 'warehouse:events:properties.$geoip_country_name',
    name: 'country',
    expression: 'properties.$geoip_country_name',
    type: 'string',
    source: { table: 'events' },
}

describe('BI editor query generation', () => {
    it('builds a visualization node with dimensions, aggregations, and filters', () => {
        const expectedQuery = [
            'SELECT',
            '    event,',
            '    sum(properties.revenue) AS sum_revenue',
            'FROM events',
            'WHERE',
            "    lower(event) LIKE lower('%sign\\'up%')",
            'GROUP BY',
            '    event',
            'ORDER BY',
            '    sum_revenue DESC',
            'LIMIT 1000',
        ].join('\n')
        const config: BIConfig = {
            source: { table: 'events' },
            chartType: ChartDisplayType.ActionsBar,
            rows: [eventField],
            columns: [],
            values: [{ field: revenueField, aggregation: 'sum' }],
            filters: [{ field: eventField, operator: 'contains', value: "sign'up" }],
            limit: 1000,
        }

        expect(buildBIQuery(config)).toEqual({
            query: expectedQuery,
            node: {
                kind: NodeKind.DataVisualizationNode,
                source: {
                    kind: NodeKind.HogQLQuery,
                    query: expectedQuery,
                    connectionId: undefined,
                },
                display: ChartDisplayType.ActionsBar,
            },
        })
    })

    it('uses a row count when no value field has been added', () => {
        const result = buildBIQuery({
            source: { table: 'events' },
            chartType: ChartDisplayType.Auto,
            rows: [eventField],
            columns: [],
            values: [],
            filters: [],
            limit: 100,
        })

        expect(result?.query).toContain('count(*) AS count')
    })

    it('maps every BI row and column dimension to pivot table axes', () => {
        const result = buildBIQuery({
            source: { table: 'events' },
            chartType: ChartDisplayType.TwoDimensionalHeatmap,
            rows: [eventField, timestampField],
            columns: [browserField, countryField],
            values: [{ field: revenueField, aggregation: 'sum' }],
            filters: [],
            limit: 50000,
        })

        expect(result?.query).toContain('toJSONString(tuple(event, timestamp)) AS bi_rows')
        expect(result?.query).toContain(
            'toJSONString(tuple(properties.$browser, properties.$geoip_country_name)) AS bi_columns'
        )
        expect(result?.query).toContain('LIMIT 1000')
        expect(result?.node.chartSettings).toEqual({
            heatmap: {
                xAxisColumn: 'bi_columns',
                yAxisColumn: 'bi_rows',
                valueColumn: 'sum_revenue',
                xAxisLabel: 'browser / country',
                yAxisLabel: 'event / timestamp',
            },
        })
    })

    it('ignores blank shelf fields until they are configured', () => {
        const blankField: BIField = {
            id: 'blank-field',
            name: '',
            expression: '',
            type: 'unknown',
            source: { table: 'events' },
        }
        const result = buildBIQuery({
            source: { table: 'events' },
            chartType: ChartDisplayType.Auto,
            rows: [blankField],
            columns: [blankField],
            values: [{ field: blankField, aggregation: 'count_distinct' }],
            filters: [{ field: blankField, operator: 'equals', value: 'signup' }],
            limit: 100,
        })

        expect(result?.query).toEqual(['SELECT', '    count(*) AS count', 'FROM events', 'LIMIT 100'].join('\n'))
    })

    it('uses a row count when a custom aggregation expression is blank', () => {
        const result = buildBIQuery({
            source: { table: 'events' },
            chartType: ChartDisplayType.Auto,
            rows: [eventField],
            columns: [],
            values: [{ field: revenueField, aggregation: 'custom', customExpression: '   ' }],
            filters: [],
            limit: 100,
        })

        expect(result?.query).toEqual(
            [
                'SELECT',
                '    event,',
                '    count(*) AS count',
                'FROM events',
                'GROUP BY',
                '    event',
                'ORDER BY',
                '    count DESC',
                'LIMIT 100',
            ].join('\n')
        )
    })

    it('keeps nested object paths and explicit SQL expressions in the generated query', () => {
        const browserField: BIField = {
            id: 'warehouse:events:properties',
            name: 'properties',
            expression: 'properties.$browser',
            type: 'json',
            source: { table: 'events' },
        }
        const result = buildBIQuery({
            source: { table: 'events' },
            chartType: ChartDisplayType.ActionsBar,
            rows: [browserField],
            columns: [],
            values: [
                {
                    field: revenueField,
                    aggregation: 'custom',
                    customExpression: "sumIf(properties.revenue, event = 'purchase')",
                },
            ],
            filters: [
                { field: timestampField, operator: 'greater_than', value: '2026-08-04 09:30:00' },
                {
                    field: browserField,
                    operator: 'custom',
                    value: '',
                    customExpression: "properties.$browser != 'HeadlessChrome'",
                },
            ],
            limit: 100,
        })

        expect(result?.query).toContain('properties.$browser')
        expect(result?.query).toContain("sumIf(properties.revenue, event = 'purchase') AS custom_revenue")
        expect(result?.query).toContain("timestamp > '2026-08-04 09:30:00'")
        expect(result?.query).toContain("properties.$browser != 'HeadlessChrome'")
    })

    test.each([
        ['events', 'timestamp'],
        ['sessions', '$start_timestamp'],
        ['heatmaps', 'timestamp'],
        ['session_replay_events', 'start_time'],
        ['raw_session_replay_events', 'min_first_timestamp'],
    ])('creates a relative date filter for the %s table', (table, expression) => {
        const filter = createDefaultDateFilter({ table })

        expect(filter).toEqual({
            field: expect.objectContaining({ expression, source: { table }, type: 'datetime' }),
            operator: 'last_7_days',
            value: '',
        })
    })

    test.each([
        ['a table without a default', { table: 'persons' }],
        ['an external table', { table: 'events', connectionId: 'warehouse-1' }],
    ])('does not create a relative date filter for %s', (_name, source) => {
        expect(createDefaultDateFilter(source)).toBeNull()
    })

    it('generates a relative date condition for the last 7 days', () => {
        const result = buildBIQuery({
            source: { table: 'events' },
            chartType: ChartDisplayType.Auto,
            rows: [],
            columns: [],
            values: [],
            filters: [{ field: timestampField, operator: 'last_7_days', value: '' }],
            limit: 100,
        })

        expect(result?.query).toContain('timestamp >= now() - INTERVAL 7 DAY')
    })

    test.each([
        ['minute', 'toStartOfMinute'],
        ['hour', 'toStartOfHour'],
        ['day', 'toStartOfDay'],
        ['week', 'toStartOfWeek'],
        ['month', 'toStartOfMonth'],
        ['quarter', 'toStartOfQuarter'],
        ['year', 'toStartOfYear'],
    ] as const)('groups date-time fields by %s', (dateBucket, dateBucketFunction) => {
        const result = buildBIQuery({
            source: { table: 'events' },
            chartType: ChartDisplayType.ActionsLineGraph,
            rows: [{ ...timestampField, dateBucket }],
            columns: [],
            values: [],
            filters: [],
            limit: 100,
        })

        expect(result?.query).toContain(`${dateBucketFunction}(timestamp)`)
    })

    test.each([
        ['id', 'integer', 'count'],
        ['uuid', 'string', 'count'],
        ['events_id', 'integer', 'count'],
        ['revenue', 'float', 'sum'],
        ['event', 'string', 'count_distinct'],
    ] as const)('uses %s fields with type %s as a %s value', (name, type, aggregation) => {
        expect(
            defaultAggregationForField({
                id: `warehouse:events:${name}`,
                name,
                expression: name,
                type,
                source: { table: 'events' },
            })
        ).toBe(aggregation)
    })

    test.each([
        ['the selected table', { table: 'events' }, { ...eventField, expression: 'properties.browser' }, true],
        ['a different table', { table: 'events' }, { ...eventField, source: { table: 'persons' } }, false],
        [
            'the same table on another connection',
            { table: 'events' },
            { ...eventField, source: { table: 'events', connectionId: '1' } },
            false,
        ],
        [
            'the selected direct connection',
            { table: 'events', connectionId: '1' },
            { ...eventField, source: { table: 'events', connectionId: '1' } },
            true,
        ],
        [
            'another direct connection with the same table',
            { table: 'events', connectionId: '1' },
            { ...eventField, source: { table: 'events', connectionId: '2' } },
            false,
        ],
    ])('accepts fields from %s according to the active source', (_name, source, field, expected) => {
        expect(isBIFieldCompatible(source, field)).toBe(expected)
    })

    const sortableConfig: BIConfig = {
        source: { table: 'events' },
        chartType: ChartDisplayType.ActionsBar,
        rows: [browserField],
        columns: [],
        values: [{ field: revenueField, aggregation: 'sum' }],
        filters: [],
        limit: 1000,
    }

    test.each([
        ['automatically by the first value, descending', undefined, 'ORDER BY\n    sum_revenue DESC'],
        [
            'by a selected dimension',
            { key: `rows:${browserField.id}`, direction: 'asc' },
            'ORDER BY\n    properties.$browser ASC',
        ],
        [
            'by a selected value',
            { key: `values:${revenueField.id}`, direction: 'asc' },
            'ORDER BY\n    sum_revenue ASC',
        ],
        [
            'automatically when the sorted field no longer exists',
            { key: 'rows:removed-field', direction: 'asc' },
            'ORDER BY\n    sum_revenue DESC',
        ],
    ] as const)('sorts %s', (_name, sort, expectedClause) => {
        expect(buildBIQuery({ ...sortableConfig, sort })?.query).toContain(expectedClause)
    })

    it('auto-sorts date dimensions newest first', () => {
        const result = buildBIQuery({ ...sortableConfig, rows: [{ ...timestampField, dateBucket: 'day' }] })

        expect(result?.query).toContain('ORDER BY\n    toStartOfDay(timestamp) DESC')
    })

    it('offers dimensions and values as sort options, and a count fallback without values', () => {
        expect(getBISortOptions(sortableConfig).map((option) => option.key)).toEqual([
            `rows:${browserField.id}`,
            `values:${revenueField.id}`,
        ])
        expect(getBISortOptions({ ...sortableConfig, values: [] }).map((option) => option.key)).toEqual([
            `rows:${browserField.id}`,
            'values:count',
        ])
        expect(getBISortOptions({ ...sortableConfig, rows: [] })).toEqual([])
    })

    it('keeps every aggregation of the same field sortable', () => {
        const twoAggregationsConfig: BIConfig = {
            ...sortableConfig,
            values: [
                { field: revenueField, aggregation: 'sum' },
                { field: revenueField, aggregation: 'average' },
            ],
        }

        expect(getBISortOptions(twoAggregationsConfig).map((option) => option.key)).toEqual([
            `rows:${browserField.id}`,
            `values:${revenueField.id}`,
            `values:${revenueField.id}:2`,
        ])
        expect(
            buildBIQuery({
                ...twoAggregationsConfig,
                sort: { key: `values:${revenueField.id}:2`, direction: 'asc' },
            })?.query
        ).toContain('ORDER BY\n    average_revenue_2 ASC')
    })

    test.each([
        ['a state persisted before sort existed', {}, null],
        [
            'an explicit sort',
            { rows: [eventField], sort: { key: `rows:${eventField.id}`, direction: 'asc' } },
            { key: `rows:${eventField.id}`, direction: 'asc' },
        ],
        ['a sort whose field was removed', { sort: { key: 'rows:removed-field', direction: 'desc' } }, null],
    ])('restores %s', (_name, configOverrides, expectedSort) => {
        const persistedConfig = { ...sortableConfig, rows: [], values: [], ...configOverrides }

        expect(parseBIEditorState(BIEditorView.BI, persistedConfig)?.config.sort).toEqual(expectedSort)
    })

    it('rejects a persisted state with a malformed sort', () => {
        expect(parseBIEditorState(BIEditorView.BI, { ...sortableConfig, sort: { key: 1, direction: 'up' } })).toBeNull()
    })

    it('keeps same-named sources and fields distinct across connections', () => {
        const sources = [
            { table: 'events' },
            { table: 'events', connectionId: 'direct-1' },
            { table: 'events', connectionId: 'direct-2' },
        ]

        expect(new Set(sources.map(getBIDataSourceKey)).size).toBe(sources.length)
        expect(new Set(sources.map((source) => getBIFieldId(source, 'event'))).size).toBe(sources.length)
    })
})
