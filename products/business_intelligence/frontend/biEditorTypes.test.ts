import { BIConfig, BIField, BIFilter } from '~/queries/schema/schema-business-intelligence'
import { NodeKind } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import {
    BIEditorView,
    DEFAULT_BI_CONFIG,
    buildBIFilterOptionsQuery,
    buildBIQuery,
    createDefaultDateFilter,
    defaultAggregationForField,
    getBIDataSourceKey,
    getBIChartFit,
    getBIDropTarget,
    getBIFieldId,
    getBISortOptions,
    getBIValueSortKey,
    getBIValuePillLabel,
    getBIFilterValidationError,
    isBIFieldCompatible,
    isBIMeasureField,
    parseBIEditorState,
} from 'products/business_intelligence/frontend/biEditorTypes'

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
    it.each(['month', 'quarter', 'year'] as const)(
        'aligns %s comparison buckets with calendar arithmetic',
        (dateBucket) => {
            const result = buildBIQuery({
                ...DEFAULT_BI_CONFIG,
                source: eventField.source,
                dateRange: { date_from: 'mStart' },
                compareFilter: { compare: true },
                rows: [{ ...timestampField, dateBucket }],
                dateField: { ...timestampField, expression: 'created_at' },
            })!
            expect(result.query).toContain(`{filters.compareDate(timestamp, '${dateBucket}')}`)
            expect(result.query).toContain('{filters.previous.native(created_at)}')
        }
    )
    test.each([undefined, '-1y'])('builds and persists period comparisons (%s)', (compare_to) => {
        const config: BIConfig = {
            ...DEFAULT_BI_CONFIG,
            source: eventField.source,
            dateRange: { date_from: 'mStart' },
            compareFilter: { compare: true, compare_to },
            rows: [{ ...timestampField, dateBucket: 'day' }],
            columns: [eventField],
            values: [{ field: revenueField, aggregation: 'sum' }],
        }
        const result = buildBIQuery(config)!
        expect(result.query).toContain('UNION ALL')
        expect(result.query).toContain('toStartOfDay({filters.compareDate(timestamp)}) AS bi_row_timestamp')
        expect(result.query).toContain('{filters.previous}')
        expect(result.query).toContain("'Current period', bi_row_timestamp, NULL")
        expect(result.query).toContain('ORDER BY bi_comparison_sort DESC, bi_row_timestamp ASC')
        expect(result.node.chartSettings?.seriesBreakdownColumn).toBe('bi_comparison')
        expect(parseBIEditorState(BIEditorView.BI, config)?.config.compareFilter).toEqual(config.compareFilter)
        expect(buildBIQuery({ ...config, dateRange: { date_from: 'all' } })?.query).not.toContain('UNION ALL')
    })

    test.each(['-28d', 'mStart', '-1mStart', 'qStart', '-1qStart', 'yStart'])(
        'keeps %s relative in query filters instead of hardcoding the date in SQL',
        (date_from) => {
            const config = { ...DEFAULT_BI_CONFIG, source: eventField.source, dateRange: { date_from } }
            const result = buildBIQuery(config)!
            expect(result.query).toContain('WHERE\n    {filters}')
            expect(result.query).not.toContain(date_from)
            expect(result.node.source.filters?.dateRange).toEqual({ date_from })
            expect(parseBIEditorState(BIEditorView.BI, config)?.config.dateRange).toEqual({
                date_from,
            })
        }
    )

    it.each([null, { ...timestampField, expression: 'created_at' }])(
        'keeps native properties with a custom date selection: %j',
        (dateField) => {
            const result = buildBIQuery({ ...DEFAULT_BI_CONFIG, source: eventField.source, dateField })!
            expect(result.query).toContain(`{filters.native(${dateField?.expression ?? 'null'})}`)
        }
    )

    it('binds raw property names, including dots, without silently choosing ambiguous columns', () => {
        const source = { table: 'orders' }
        const field = { ...eventField, source, name: 'properties.plan.tier', expression: 'properties.`plan.tier`' }
        const state = { ...DEFAULT_BI_CONFIG, source, rows: [field] }
        expect(buildBIQuery(state)?.query).toContain("(properties.`plan.tier`) AS 'plan.tier'")
        const ambiguous = buildBIQuery({
            ...state,
            columns: [{ ...field, name: 'person_properties.plan.tier', expression: 'person_properties.`plan.tier`' }],
        })!
        expect(ambiguous.query).not.toContain("AS 'plan.tier'")
    })

    it('maps warehouse dates and dashboard properties to unbucketed worksheet fields', () => {
        const source = { table: 'orders', connectionId: 'example-connection' }
        const result = buildBIQuery({
            ...DEFAULT_BI_CONFIG,
            source,
            dateField: { ...timestampField, source, expression: 'created_at', dateBucket: 'month' },
            dateRange: { date_from: '-30d' },
            rows: [{ ...eventField, source, name: 'plan', expression: 'subscription_plan' }],
        })!
        expect(result.query).toContain("{filters((created_at) AS 'timestamp', (subscription_plan) AS 'plan')}")
        expect(result.node.source.connectionId).toBe(source.connectionId)
        expect(result.node.source.filters?.dateRange?.date_from).toBe('-30d')
    })
    test.each<{ filter: BIFilter; expected: string | null }>([
        {
            filter: { field: eventField, operator: 'in', value: '', values: ["sign'up", 'a,b', ''] },
            expected: "event IN ('sign\\'up', 'a,b', '')",
        },
        {
            filter: { field: revenueField, operator: 'not_in', value: '', values: ['0', '12.5'] },
            expected: 'properties.revenue NOT IN (0, 12.5)',
        },
        {
            filter: {
                field: revenueField,
                operator: 'in',
                value: '',
                values: ['9007199254740993', '-0.1234567890123456789', '1e3', '010', '+002.5'],
            },
            expected: 'properties.revenue IN (9007199254740993, -0.1234567890123456789, 1e3, 10, +2.5)',
        },
        {
            filter: {
                field: revenueField,
                operator: 'between',
                value: '9007199254740993',
                valueTo: '9007199254740995',
            },
            expected: '(properties.revenue >= 9007199254740993 AND properties.revenue <= 9007199254740995)',
        },
        { filter: { field: eventField, operator: 'in', value: '', values: [] }, expected: null },
        {
            filter: { field: revenueField, operator: 'between', value: '0', valueTo: '20.5' },
            expected: '(properties.revenue >= 0 AND properties.revenue <= 20.5)',
        },
        {
            filter: { field: revenueField, operator: 'between', value: '', valueTo: '20' },
            expected: '(properties.revenue <= 20)',
        },
        { filter: { field: revenueField, operator: 'between', value: '5' }, expected: '(properties.revenue >= 5)' },
        { filter: { field: revenueField, operator: 'between', value: '' }, expected: null },
        {
            filter: {
                field: timestampField,
                operator: 'between',
                value: '2026-06-01 00:00:00',
                valueTo: '2026-06-07 23:59:59',
            },
            expected: "(timestamp >= '2026-06-01 00:00:00' AND timestamp <= '2026-06-07 23:59:59')",
        },
        {
            filter: { field: eventField, operator: 'custom', value: '', customExpression: '1 = 0', enabled: false },
            expected: null,
        },
        { filter: { field: timestampField, operator: 'last_7_days', value: '', enabled: false }, expected: null },
    ])('builds and restores quick filter $filter.operator ($expected)', ({ filter, expected }) => {
        const config = { ...DEFAULT_BI_CONFIG, source: eventField.source, filters: [filter] }
        const restored = parseBIEditorState(BIEditorView.BI, JSON.stringify(config))
        expect(restored?.config.filters).toEqual([filter])
        const query = buildBIQuery(restored!.config)!.query
        if (expected) {
            expect(query).toContain(`AND (${expected})`)
        } else {
            expect(query).toContain('WHERE\n    {filters}\nLIMIT')
        }
    })

    test.each(['abc', 'NaN', 'Infinity', '1e999', '0x10', '1 OR 1 = 1'])(
        'blocks invalid numeric filters without emitting SQL for %s',
        (value) => {
            for (const filter of [
                { field: revenueField, operator: 'in', value: '', values: ['1', value] },
                { field: revenueField, operator: 'between', value: '0', valueTo: value },
                { field: revenueField, operator: 'equals', value },
            ] satisfies BIFilter[]) {
                const config = {
                    ...DEFAULT_BI_CONFIG,
                    source: eventField.source,
                    filters: [filter, { field: eventField, operator: 'in' as const, value: '' }],
                }
                expect(getBIFilterValidationError(filter)).toBeTruthy()
                expect(buildBIQuery(config)).toBeNull()
                expect(buildBIFilterOptionsQuery(config, 1)).toBeNull()
                expect(buildBIQuery({ ...config, filters: [{ ...filter, enabled: false }] })).not.toBeNull()
            }
        }
    )

    it('scopes value suggestions to other enabled filters and the selected connection', () => {
        const source = { table: 'orders', connectionId: 'example-connection' }
        const config: BIConfig = {
            ...DEFAULT_BI_CONFIG,
            source,
            filters: [
                { field: { ...eventField, source }, operator: 'in', value: '', values: ['purchase'] },
                { field: { ...revenueField, source }, operator: 'between', value: '10', valueTo: '100' },
                { field: { ...timestampField, source }, operator: 'last_7_days', value: '', enabled: false },
            ],
        }
        expect(buildBIFilterOptionsQuery(config, 0)).toEqual({
            kind: NodeKind.HogQLQuery,
            connectionId: source.connectionId,
            filters: { dateRange: { date_from: 'all' } },
            query: "SELECT DISTINCT toString(event) AS value\nFROM orders\nWHERE ({filters((null) AS 'timestamp', (event) AS 'event', (properties.revenue) AS 'revenue')}) AND (event IS NOT NULL) AND ((properties.revenue >= 10 AND properties.revenue <= 100))\nLIMIT 100",
        })
        config.filters.push({
            field: { ...eventField, expression: '', name: '', source },
            operator: 'custom',
            value: '',
            customExpression: 'revenue > 20 OR revenue = 0',
        })
        expect(buildBIFilterOptionsQuery(config, 0)?.query).toContain('AND (revenue > 20 OR revenue = 0)')
    })

    test.each([{ values: [1] }, { values: 'purchase' }, { valueTo: 10 }, { enabled: 'false' }])(
        'rejects malformed quick filter state %j',
        (invalid) => {
            expect(
                parseBIEditorState(BIEditorView.BI, {
                    ...DEFAULT_BI_CONFIG,
                    source: eventField.source,
                    filters: [{ field: eventField, operator: 'in', value: '', ...invalid }],
                })
            ).toBeNull()
        }
    )

    it('builds a visualization node with dimensions, aggregations, and filters', () => {
        const expectedQuery = [
            'SELECT',
            '    event,',
            '    sum(properties.revenue) AS sum_revenue',
            'FROM events',
            'WHERE',
            '    {filters}',
            "    AND (lower(event) LIKE lower('%sign\\'up%'))",
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
                    filters: { dateRange: { date_from: 'all' } },
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

    it.each([
        { chartType: ChartDisplayType.ActionsBar, rows: [], columns: [timestampField, browserField], values: [] },
        { chartType: ChartDisplayType.ActionsStackedBar, rows: [browserField], columns: [timestampField], values: [] },
        { chartType: ChartDisplayType.ActionsLineGraph, rows: [timestampField, browserField], columns: [], values: [] },
        { chartType: ChartDisplayType.ActionsAreaGraph, rows: [timestampField], columns: [browserField], values: [] },
        {
            chartType: ChartDisplayType.Auto,
            rows: [browserField],
            columns: [timestampField],
            values: [{ field: revenueField, aggregation: 'sum' as const }],
        },
    ])('maps two dimensions to an axis and a breakdown for $chartType', ({ chartType, rows, columns, values }) => {
        const result = buildBIQuery({
            ...DEFAULT_BI_CONFIG,
            source: { table: 'events' },
            chartType,
            rows: rows.map((field) => (field === timestampField ? { ...field, dateBucket: 'day' } : field)),
            columns: columns.map((field) => (field === timestampField ? { ...field, dateBucket: 'day' } : field)),
            values,
        })!

        const settings = result.node.chartSettings!
        expect(result.query).toContain(`toStartOfDay(timestamp) AS ${settings.xAxis!.column}`)
        expect(result.query).toContain(`properties.$browser AS ${settings.seriesBreakdownColumn}`)
        expect(settings.xAxis!.column).not.toBe(settings.seriesBreakdownColumn)
        expect(settings.yAxis).toEqual([{ column: values.length ? 'sum_revenue' : 'count' }])
        expect(result.node.display).toBe(chartType)
    })

    it('keeps a numeric column dimension on the x-axis instead of treating it as a measure', () => {
        const result = buildBIQuery({
            ...DEFAULT_BI_CONFIG,
            source: { table: 'events' },
            chartType: ChartDisplayType.ActionsStackedBar,
            rows: [browserField],
            columns: [revenueField],
        })!

        expect(result.node.chartSettings).toEqual({
            xAxis: { column: 'bi_column_revenue' },
            xAxisLabel: 'revenue',
            yAxis: [{ column: 'count' }],
            seriesBreakdownColumn: 'bi_row_browser',
            showLegend: true,
        })
        expect(result.query).toContain('properties.revenue AS bi_column_revenue')
    })

    it.each(['rows', 'columns'] as const)('disambiguates colliding dimension aliases on %s', (shelf) => {
        const result = buildBIQuery({
            ...DEFAULT_BI_CONFIG,
            source: { table: 'events' },
            chartType: ChartDisplayType.ActionsStackedBar,
            [shelf]: [{ ...eventField, name: 'browser_2' }, browserField],
        })!

        const { xAxis, seriesBreakdownColumn } = result.node.chartSettings!
        expect(xAxis!.column).not.toBe(seriesBreakdownColumn)
        expect(result.query).toContain(`event AS ${xAxis!.column}`)
        expect(result.query).toContain(`properties.$browser AS ${seriesBreakdownColumn}`)
    })

    it.each([100, 1000, 10000, 50000] as const)(
        'maps every BI row and column dimension to pivot table axes with limit %i',
        (limit) => {
            const result = buildBIQuery({
                source: { table: 'events' },
                chartType: ChartDisplayType.TwoDimensionalHeatmap,
                rows: [eventField, timestampField],
                columns: [browserField, countryField],
                values: [{ field: revenueField, aggregation: 'sum' }],
                filters: [],
                limit,
            })

            expect(result?.query).toContain('event AS bi_row_event, timestamp AS bi_row_timestamp_2')
            expect(result?.query).toContain('properties.$browser AS bi_column_browser')
            expect(result?.query).toContain('properties.$geoip_country_name AS bi_column_country_2')
            expect(result?.query).toMatch(/toJSONString\(tuple\(.*\)\) AS bi_rows/)
            expect(result?.query).toMatch(/toJSONString\(tuple\(.*\)\) AS bi_columns/)
            expect(result?.query).toContain(`LIMIT ${limit}`)
            expect(result?.node.chartSettings).toMatchObject({
                heatmap: {
                    xAxisColumn: 'bi_columns',
                    yAxisColumn: 'bi_rows',
                    valueColumn: 'sum_revenue',
                    xAxisLabel: 'browser / country',
                    yAxisLabel: 'event / timestamp',
                },
            })
        }
    )

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

        expect(result?.query).toEqual(
            ['SELECT', '    count(*) AS count', 'FROM events', 'WHERE', '    {filters}', 'LIMIT 100'].join('\n')
        )
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
                'WHERE',
                '    {filters}',
                'GROUP BY',
                '    event',
                'ORDER BY',
                '    count DESC',
                'LIMIT 100',
            ].join('\n')
        )
    })

    test.each([
        [undefined, 'custom_revenue'],
        ['ARPU', 'ARPU'],
        ['Revenue per user', '"Revenue per user"'],
        ['`Revenue`', '"`Revenue`"'],
        ['Revenue"quoted`', '`Revenue"quoted```'],
        ['properties', 'properties_2'],
        ['event', 'event_2'],
    ])('keeps SQL expressions and measure label %s through persistence', (label, alias) => {
        const browserField: BIField = {
            id: 'warehouse:events:properties',
            name: 'properties',
            expression: 'properties.$browser',
            type: 'json',
            source: { table: 'events' },
        }
        const config: BIConfig = {
            source: { table: 'events' },
            chartType: ChartDisplayType.ActionsBar,
            rows: [browserField],
            columns: [],
            values: [
                {
                    field: revenueField,
                    aggregation: 'custom',
                    customExpression: "sumIf(properties.revenue, event = 'purchase')",
                    label,
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
        }
        const restored = parseBIEditorState(BIEditorView.BI, JSON.stringify(config))!.config
        const result = buildBIQuery(restored)

        expect(result?.query).toContain('properties.$browser')
        expect(result?.query).toContain(`sumIf(properties.revenue, event = 'purchase') AS ${alias}`)
        expect(getBIValuePillLabel(restored.values[0])).toBe(label ?? "sumIf(properties.revenue, event = 'purchase')")
        expect(getBISortOptions(restored).at(-1)?.label).toBe(label ?? "sumIf(properties.revenue, event = 'purchase')")
        expect(result?.query).toContain("timestamp > '2026-08-04 09:30:00'")
        expect(result?.query).toContain("properties.$browser != 'HeadlessChrome'")
    })

    test.each([ChartDisplayType.ActionsTable, ChartDisplayType.TwoDimensionalHeatmap])(
        'disambiguates measure names from dimensions and generated aliases in %s',
        (chartType) => {
            const config: BIConfig = {
                ...DEFAULT_BI_CONFIG,
                source: eventField.source,
                chartType,
                rows: [eventField],
                values: [
                    {
                        field: revenueField,
                        aggregation: 'custom',
                        customExpression: 'sum(properties.revenue)',
                        label: 'sum_revenue_2',
                    },
                    { field: revenueField, aggregation: 'sum' },
                    { field: revenueField, aggregation: 'custom', customExpression: 'count(*)', label: 'event' },
                ],
                sort: { key: `values:${revenueField.id}:2`, direction: 'asc' },
            }
            const result = buildBIQuery(config)!
            expect(result.query).toContain('sum(properties.revenue) AS sum_revenue_2,')
            expect(result.query).toContain('sum(properties.revenue) AS sum_revenue_2_2,')
            expect(result.query).toMatch(/ORDER BY\s+sum_revenue_2_2 ASC/)
            expect(getBISortOptions(config).find(({ key }) => key === config.sort?.key)?.expression).toBe(
                'sum_revenue_2_2'
            )
            if (chartType === ChartDisplayType.TwoDimensionalHeatmap) {
                expect(result.node.chartSettings?.heatmap?.valueColumn).toBe('sum_revenue_2')
            }
        }
    )

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

    it('migrates the legacy default date filter into dashboard-aware query filters', () => {
        const config: BIConfig = {
            source: { table: 'events' },
            chartType: ChartDisplayType.Auto,
            rows: [],
            columns: [],
            values: [],
            filters: [createDefaultDateFilter({ table: 'events' })!],
            limit: 100,
        }
        const result = buildBIQuery(config)

        expect(result?.query).toContain('{filters}')
        expect(result?.query).not.toContain('INTERVAL 7 DAY')
        expect(result?.node.source.filters?.dateRange).toEqual({ date_from: '-7d' })
        expect(parseBIEditorState(BIEditorView.BI, config)?.config.filters).toEqual([])
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
        expect([0, 1].map((index) => getBIValueSortKey(twoAggregationsConfig, index))).toEqual([
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

    const userIdField: BIField = { ...revenueField, id: 'warehouse:events:user_id', name: 'user_id', type: 'integer' }

    test.each([
        ['userId', false],
        ['accountId', false],
        ['userID', false],
        ['accountUuid', false],
        ['accountUUID', false],
        ['USER_ID', false],
        ['UUID', false],
        ['grid', true],
        ['paid', true],
    ])('classifies numeric field %s as a measure: %s', (name, isMeasure) => {
        const field = { ...userIdField, name }
        expect(isBIMeasureField(field)).toBe(isMeasure)
        expect(getBIDropTarget(field, 'rows').shelf).toBe(isMeasure ? 'values' : 'rows')
    })

    test.each([0, 1, 2])('checks pivot fit with %i measures', (measureCount) => {
        const pivotConfig: BIConfig = {
            ...sortableConfig,
            chartType: ChartDisplayType.TwoDimensionalHeatmap,
            rows: [browserField],
            columns: [countryField],
            values: Array.from({ length: measureCount }, () => ({ field: revenueField, aggregation: 'sum' })),
        }
        expect(getBIChartFit(pivotConfig, ChartDisplayType.TwoDimensionalHeatmap).fits).toBe(true)
        expect(buildBIQuery(pivotConfig)?.node.chartSettings?.heatmap?.valueColumn).toBe(
            measureCount === 0 ? 'count' : 'sum_revenue'
        )
    })

    test.each([
        ['a measure dropped on rows becomes a value', revenueField, 'rows', revenueField, 'values'],
        ['a measure dropped on columns becomes a value', revenueField, 'columns', revenueField, 'values'],
        ['a measure dropped on filters stays a filter', revenueField, 'filters', revenueField, 'filters'],
        ['a numeric identifier stays a dimension', userIdField, 'rows', userIdField, 'rows'],
        [
            'a timestamp on rows is bucketed by day',
            timestampField,
            'rows',
            { ...timestampField, dateBucket: 'day' },
            'rows',
        ],
        [
            'a bucketed timestamp keeps its bucket',
            { ...timestampField, dateBucket: 'month' },
            'columns',
            { ...timestampField, dateBucket: 'month' },
            'columns',
        ],
    ] as const)('routes a dropped field: %s', (_, field, shelf, expectedField, expectedShelf) => {
        expect(getBIDropTarget(field as BIField, shelf)).toEqual({ field: expectedField, shelf: expectedShelf })
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
