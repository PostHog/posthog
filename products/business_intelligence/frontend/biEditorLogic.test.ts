import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'

import { useMocks } from '~/mocks/jest'
import * as queryRunner from '~/queries/query'
import { BIConfig, BIField } from '~/queries/schema/schema-business-intelligence'
import { HogQLMetadataResponse } from '~/queries/schema/schema-general'
import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { ChartDisplayType } from '~/types'

import { biConnectionsLogic } from './biConnectionsLogic'
import { biEditorLogic } from './biEditorLogic'
import { BIEditorView, buildBIQuery, getBIFieldPillLabel, parseBIEditorState } from './biEditorTypes'
import { biMetricParametersLogic } from './biMetricParametersLogic'

describe('biEditorLogic', () => {
    const TAB_ID = 'bi-test'
    let databaseLogic: ReturnType<typeof databaseTableListLogic.build>
    let queryEndpointMock: jest.Mock
    beforeEach(() => {
        localStorage.clear()
        sessionStorage.clear()
        queryEndpointMock = jest.fn(() => [200, { tables: {}, joins: [] }])
        useMocks({
            get: {
                '/api/projects/:team_id/external_data_sources/connections/': [],
                '/api/projects/:team_id/warehouse_saved_queries/': { results: [] },
            },
            post: {
                '/api/environments/:team_id/query/': queryEndpointMock,
                '/api/projects/:team_id/query/HogQLMetadata/': {
                    isValid: true,
                    errors: [],
                    warnings: [],
                    notices: [],
                    output_columns: [{ name: 'value', type: 'String' }],
                },
            },
        })
        initKeaTests()
        router.actions.push('/')
        databaseLogic = databaseTableListLogic()
        databaseLogic.mount()
    })
    afterEach(() => databaseLogic.unmount())
    const eventField: BIField = {
        id: 'warehouse:events:event',
        name: 'event',
        expression: 'event',
        type: 'string',
        source: { table: 'events' },
    }
    const config: BIConfig = {
        source: { table: 'events' },
        chartType: ChartDisplayType.ActionsBar,
        rows: [eventField],
        columns: [],
        values: [],
        filters: [{ field: eventField, operator: 'equals', value: 'signup' }],
        limit: 1000,
        sort: null,
    }
    it('edits snapshot parameters as typed bound values, with cancellation and stale-draft protection', async () => {
        const logic = biEditorLogic({ tabId: TAB_ID })
        const parameters = biMetricParametersLogic({ tabId: TAB_ID })
        logic.mount()
        parameters.mount()
        logic.actions.setAutoUpdate(false)
        const querySnapshot = {
            kind: NodeKind.HogQLQuery as const,
            query: 'SELECT {cohort} AS cohort, {minimum} AS minimum, {include_trial} AS include_trial',
            values: {
                cohort: 'paid',
                minimum: 10,
                include_trial: true,
                ids: [1, 2],
                missing: null,
                ['__proto__']: 'paid',
                constructor: 5,
            },
        }
        logic.actions.restoreState({ editorView: BIEditorView.BI, config: { ...config, querySnapshot } })
        parameters.actions.open()
        expect(parameters.values.parameters.map(({ name }) => name)).toEqual([
            'cohort',
            'minimum',
            'include_trial',
            '__proto__',
            'constructor',
        ])
        expect(parameters.values.parameterErrors['__proto__']).toBeUndefined()
        expect(parameters.values.parameterErrors['constructor']).toBeUndefined()
        parameters.actions.changeParameter('constructor', '')
        expect(parameters.values.parameterErrors['constructor']).toBe('Enter a valid number')
        parameters.actions.changeParameter('constructor', '5')
        expect(parameters.values.parameterErrors['constructor']).toBeUndefined()
        parameters.actions.changeParameter('minimum', '')
        expect(parameters.values.parameterErrors).toEqual({ minimum: 'Enter a valid number' })
        parameters.actions.apply()
        expect(logic.values.config.querySnapshot).toEqual(querySnapshot)
        parameters.actions.close()
        parameters.actions.open()
        expect(parameters.values.parameters.find(({ name }) => name === 'minimum')?.value).toBe('10')
        const literal = "paid' OR 1=1 --"
        parameters.actions.changeParameter('cohort', literal)
        parameters.actions.changeParameter('minimum', '25.5')
        parameters.actions.changeParameter('include_trial', false)
        await expectLogic(logic, () => parameters.actions.apply()).toDispatchActions([
            'setSnapshotParameters',
            'runAfterChange',
        ])
        expect(buildBIQuery(logic.values.config)?.node.source).toMatchObject({
            query: querySnapshot.query,
            values: { ...querySnapshot.values, cohort: literal, minimum: 25.5, include_trial: false },
        })
        expect(parameters.values.source).toBeNull()
        parameters.actions.open()
        logic.actions.restoreState({ editorView: BIEditorView.BI, config: { ...config, querySnapshot } })
        expect(parameters.values.applyDisabledReason).toContain('worksheet changed')
        parameters.actions.apply()
        expect(logic.values.config.querySnapshot).toEqual(querySnapshot)
        parameters.unmount()
        logic.unmount()
    })
    it.each(['sum(properties.amount)', 'sum(properties.amount) / nullIf(count(), 0)'])(
        'saves a custom measure expression without the previous count wrapper: %s',
        (expression) => {
            const logic = biEditorLogic({ tabId: TAB_ID })
            logic.mount()
            logic.actions.setAutoUpdate(false)
            const measure = { field: eventField, aggregation: 'count' as const, formatting: { decimalPlaces: 2 } }
            logic.actions.restoreState({
                editorView: BIEditorView.BI,
                config: { ...config, values: [measure, measure] },
            })

            logic.actions.setMeasureExpression(0, expression, 'custom')

            expect(logic.values.config.values[0]).toEqual({
                ...measure,
                aggregation: 'custom',
                customExpression: expression,
            })
            expect(logic.values.config.values[1]).toEqual(measure)
            expect(buildBIQuery(logic.values.config)!.query).toContain(`${expression} AS`)
            expect(buildBIQuery(logic.values.config)!.query).not.toContain(`count(${expression})`)

            logic.actions.setMeasureExpression(0, 'properties.amount', 'sum')
            expect(buildBIQuery(logic.values.config)!.query).toContain('sum(properties.amount) AS')
            expect(logic.values.config.values[0].formatting).toEqual(measure.formatting)
            logic.unmount()
        }
    )
    it.each(['rows', 'columns'] as const)('only adds a calculated field to %s after confirmation', async (shelf) => {
        const logic = biEditorLogic({ tabId: TAB_ID })
        logic.mount()
        logic.actions.setAutoUpdate(false)
        logic.actions.restoreState({ editorView: BIEditorView.BI, config })
        logic.actions.editCalculatedField(undefined, shelf)
        expect(logic.values.config).toEqual(config)
        logic.actions.setCalculatedMeasureDraft(null)
        expect(logic.values.config).toEqual(config)
        logic.actions.editCalculatedField(undefined, shelf)
        logic.actions.setCalculatedMeasureDraft({
            ...logic.values.calculatedMeasureDraft!,
            name: 'Event label',
            expression: 'lower(event)',
        })
        expect(logic.values.config).toEqual(config)
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.saveCalculatedMeasure()
        expect(logic.values.config[shelf].at(-1)).toMatchObject({ name: 'Event label', expression: 'lower(event)' })
        expect(logic.values.calculatedMeasureDraft).toBeNull()
        logic.unmount()
    })
    it('infers SQL types, preserves an explicit override, and blocks invalid calculations', async () => {
        useMocks({
            post: {
                '/api/projects/:team_id/query/HogQLMetadata/': {
                    isValid: true,
                    errors: [],
                    warnings: [],
                    notices: [],
                    output_columns: [{ name: 'value', type: 'Nullable(Float64)' }],
                },
            },
        })
        const logic = biEditorLogic({ tabId: TAB_ID })
        logic.mount()
        logic.actions.restoreState({ editorView: BIEditorView.BI, config })
        logic.actions.setCalculatedMeasureDraft({
            index: null,
            kind: 'dimension',
            name: 'Amount',
            expression: 'toFloat(event)',
        })
        expect(logic.values.calculatedFieldValidation).toBe('checking')
        logic.actions.saveCalculatedMeasure()
        expect(logic.values.config.localFields).toBeUndefined()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.calculatedMeasureDraft?.type).toBe('float')
        expect(logic.values.calculatedFieldValidation).toBe('valid')
        logic.actions.setCalculatedMeasureDraft({
            ...logic.values.calculatedMeasureDraft!,
            type: 'string',
            typeOverride: true,
        })
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.calculatedMeasureDraft?.type).toBe('string')
        useMocks({
            post: {
                '/api/projects/:team_id/query/HogQLMetadata/': {
                    isValid: false,
                    errors: [{ message: 'Unknown field' }],
                    warnings: [],
                    notices: [],
                },
            },
        })
        logic.actions.setCalculatedMeasureDraft({
            ...logic.values.calculatedMeasureDraft!,
            expression: 'missing_field',
        })
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.calculatedFieldValidation).toBe('invalid')
        logic.actions.saveCalculatedMeasure()
        expect(logic.values.config.localFields).toBeUndefined()
        logic.unmount()
    })

    it('keeps cached validation when a superseded expression finishes after undo', async () => {
        const validMetadata: HogQLMetadataResponse = {
            isValid: true,
            errors: [],
            warnings: [],
            notices: [],
            output_columns: [{ name: 'value', type: 'String' }],
        }
        let finishPending!: (metadata: HogQLMetadataResponse) => void
        const pending = new Promise<HogQLMetadataResponse>((resolve) => {
            finishPending = resolve
        })
        const performQuery = jest
            .spyOn(queryRunner, 'performQuery')
            .mockResolvedValueOnce(validMetadata as never)
            .mockImplementationOnce(() => pending as never)
        const logic = biEditorLogic({ tabId: TAB_ID })
        logic.mount()
        logic.actions.setAutoUpdate(false)
        logic.actions.restoreState({ editorView: BIEditorView.BI, config })
        const draft = { index: null, kind: 'dimension' as const, name: 'Label', expression: 'event' }
        try {
            logic.actions.setCalculatedMeasureDraft(draft)
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.calculatedFieldValidation).toBe('valid')
            jest.useFakeTimers()
            logic.actions.setCalculatedMeasureDraft({ ...draft, expression: 'lower(event)' })
            await jest.advanceTimersByTimeAsync(300)
            expect(performQuery).toHaveBeenCalledTimes(2)
            logic.actions.setCalculatedMeasureDraft(draft)
            await jest.advanceTimersByTimeAsync(0)
            expect(logic.values.calculatedFieldValidation).toBe('valid')
            finishPending(validMetadata)
            await jest.advanceTimersByTimeAsync(0)
            expect(logic.values.calculatedFieldMetadata?.expression).toBe('event')
            expect(logic.values.calculatedFieldValidation).toBe('valid')
        } finally {
            finishPending(validMetadata)
            logic.unmount()
            performQuery.mockRestore()
            jest.useRealTimers()
        }
    })

    it('renames shelf labels without changing the source expression and preserves them on reload', () => {
        const logic = biEditorLogic({ tabId: TAB_ID })
        logic.mount()
        logic.actions.setAutoUpdate(false)
        logic.actions.restoreState({ editorView: BIEditorView.BI, config })
        logic.actions.renameField('rows', 0, 'Activity')
        const restored = parseBIEditorState(BIEditorView.BI, JSON.stringify(logic.values.config))!.config
        expect(restored.rows[0]).toMatchObject({ name: 'event', label: 'Activity', expression: 'event' })
        const node = buildBIQuery(restored)!.node
        expect(node.chartSettings?.xAxisLabel).toBe('Activity')
        expect(node.tableSettings?.columns?.[0].settings?.display?.label).toBe('Activity')
        const warehouse = { ...restored, source: { table: 'orders' }, filters: [] }
        expect(buildBIQuery(warehouse)!.query).toContain("(event) AS 'event'")
        expect(buildBIQuery(warehouse)!.query).not.toContain("AS 'Activity'")
        logic.actions.startSuggestedChart()
        expect(logic.values.config.rows).toEqual(restored.rows)
        logic.actions.resetConfig()
        logic.actions.startSuggestedChart()
        expect(logic.values.config.values[0]).toMatchObject({ customExpression: 'count(*)', shelf: 'rows' })
        logic.actions.resetConfig()
        databaseLogic.actions.loadDatabaseSuccess({
            tables: {
                events: {
                    id: 'events',
                    name: 'events',
                    type: 'posthog',
                    fields: {
                        timestamp: {
                            name: 'timestamp',
                            type: 'datetime',
                            schema_valid: true,
                            hogql_value: 'timestamp',
                        },
                    },
                },
            },
            joins: [],
        })
        logic.actions.startSuggestedChart()
        expect(logic.values.config.columns[0]).toMatchObject({ name: 'timestamp', dateBucket: 'day' })
        expect(logic.values.config.chartType).toBe(ChartDisplayType.ActionsLineGraph)
        logic.unmount()
    })
    it.each([
        ['remove', 0],
        ['remove', 1],
        ['remove', 2],
        ['reorder', 0],
        ['reorder', 1],
        ['reorder', 2],
    ] as const)('keeps Top N and result filters attached when %s changes value %s', (operation, index) => {
        const logic = biEditorLogic({ tabId: TAB_ID })
        logic.mount()
        logic.actions.setAutoUpdate(false)
        logic.actions.restoreState({
            editorView: BIEditorView.BI,
            config: {
                ...config,
                values: [0, 1, 2].map((value) => ({
                    field: { ...eventField, id: `measure-${value}`, expression: `properties.value_${value}` },
                    aggregation: 'sum',
                })),
                topN: { fieldId: eventField.id, count: 5, measureIndex: 1, includeOther: false },
                resultFilters: [0, 1, 2].map((measureIndex) => ({
                    id: `filter-${measureIndex}`,
                    measureIndex,
                    operator: 'greater_than',
                    value: '5',
                })),
            },
        })
        if (operation === 'remove') {
            logic.actions.removeFieldFromShelf('values', index)
        } else {
            logic.actions.moveFieldToShelf('values', index, 'values', index === 0 ? 3 : 0)
        }
        expect(logic.values.config.resultFilters).toHaveLength(operation === 'remove' ? 2 : 3)
        for (const filter of logic.values.config.resultFilters!) {
            expect(logic.values.config.values[filter.measureIndex].field.id).toBe(
                filter.id.replace('filter-', 'measure-')
            )
        }
        if (index === 1 && operation === 'remove') {
            expect(logic.values.config.topN).toBeUndefined()
        } else {
            const measureIndex = logic.values.config.topN!.measureIndex
            expect(logic.values.config.values[measureIndex].field.id).toBe('measure-1')
        }
        logic.unmount()
    })

    it('reorders dimension pills and swaps measures without losing their calculations or placement on reload', () => {
        const logic = biEditorLogic({ tabId: TAB_ID })
        logic.mount()
        const category = { ...eventField, id: 'category', name: 'Category', expression: 'properties.category' }
        const revenue = {
            field: { ...eventField, id: 'revenue', expression: 'properties.revenue' },
            aggregation: 'sum' as const,
            tableCalculation: { type: 'running_total' as const },
        }
        logic.actions.restoreState({
            editorView: BIEditorView.BI,
            config: {
                ...config,
                columns: [eventField, category],
                rows: [],
                values: [revenue],
                sort: { key: `columns:${category.id}`, direction: 'asc' },
            },
        })
        logic.actions.moveFieldToShelf('columns', 1, 'columns', 0)
        expect(logic.values.config.columns).toEqual([category, eventField])
        logic.actions.swapRowsAndColumns()
        expect(logic.values.config.rows).toEqual([category, eventField])
        expect(logic.values.config.columns).toEqual([])
        expect(logic.values.config.values).toEqual([{ ...revenue, shelf: 'columns' }])
        expect(logic.values.config.sort?.key).toBe(`rows:${category.id}`)
        expect(logic.values.config.chartType).toBe(ChartDisplayType.ActionsBarValue)
        expect(parseBIEditorState(BIEditorView.BI, JSON.stringify(logic.values.config))?.config.values).toEqual(
            logic.values.config.values
        )
        logic.actions.moveFieldToShelf('values', 0, 'rows')
        expect(logic.values.config.values).toEqual([{ ...revenue, shelf: 'rows' }])
        logic.actions.convertMeasureToDimension(0)
        expect(logic.values.config.values).toEqual([])
        expect(logic.values.config.rows).toEqual([category, eventField, revenue.field])
        logic.unmount()
    })

    it.each(['rows', 'columns'] as const)('copies a timeline field into %s without changing the original', (target) => {
        const logic = biEditorLogic({ tabId: TAB_ID })
        logic.mount()
        const date = {
            ...eventField,
            id: 'date',
            name: 'timestamp',
            expression: 'timestamp',
            type: 'datetime' as const,
            dateBucket: 'month' as const,
        }
        logic.actions.restoreState({
            editorView: BIEditorView.BI,
            config: { ...config, rows: [date], columns: [], values: [] },
        })
        logic.actions.duplicateField('rows', 0, target, 0)
        logic.actions.setFieldDatePart(target, 0, 'month')
        expect(logic.values.config.rows[target === 'rows' ? 1 : 0]).toEqual(date)
        expect(logic.values.config[target][0].id).not.toBe(date.id)
        expect(logic.values.generatedQuery?.query).toContain('toStartOfMonth(timestamp)')
        expect(logic.values.generatedQuery?.query).toContain('toMonth(timestamp)')
        const restored = parseBIEditorState(BIEditorView.BI, JSON.stringify(logic.values.config))!
        expect(restored.config[target][0].datePart).toBe('month')
        logic.actions.setFieldDateBucket(target, 0, 'year')
        expect(logic.values.config[target][0].datePart).toBeUndefined()
        expect(logic.values.generatedQuery?.query).toContain('toStartOfYear(timestamp)')
        logic.unmount()
    })

    it('copies a calculated measure at the drop position and keeps filters attached to the original', () => {
        const logic = biEditorLogic({ tabId: TAB_ID })
        logic.mount()
        logic.actions.setAutoUpdate(false)
        const measure = {
            field: { ...eventField, type: 'float' as const },
            aggregation: 'custom' as const,
            customExpression: 'sum(revenue) / nullIf(count(), 0)',
            label: 'Revenue per event',
            shelf: 'columns' as const,
            tableCalculation: { type: 'running_total' as const },
        }
        logic.actions.restoreState({
            editorView: BIEditorView.BI,
            config: {
                ...config,
                values: [measure],
                resultFilters: [{ id: 'original', measureIndex: 0, operator: 'greater_than', value: '5' }],
                topN: { fieldId: eventField.id, count: 5, measureIndex: 0, includeOther: false },
            },
        })
        logic.actions.duplicateField('values', 0, 'values', 0)
        expect(logic.values.config.values).toEqual([measure, measure])
        expect(logic.values.config.resultFilters?.[0].measureIndex).toBe(1)
        expect(logic.values.config.topN?.measureIndex).toBe(1)
        logic.actions.duplicateField('values', 0, 'rows')
        expect(logic.values.config.values).toEqual([measure, measure, { ...measure, shelf: 'rows' }])
        logic.unmount()
    })

    it.each(['field', 'blank', 'calculation', 'move'] as const)(
        'preserves a Count result filter when adding the first measure via %s',
        (method) => {
            const logic = biEditorLogic({ tabId: TAB_ID })
            logic.mount()
            logic.actions.restoreState({
                editorView: BIEditorView.BI,
                config: {
                    ...config,
                    chartType: ChartDisplayType.ActionsTable,
                    resultFilters: [{ id: 'count-filter', measureIndex: 0, operator: 'greater_than', value: '5' }],
                },
            })
            if (method === 'field') {
                logic.actions.addFieldToShelf(eventField, 'values')
            } else if (method === 'blank') {
                logic.actions.addBlankFieldToShelf('values')
                logic.actions.setFieldExpression('values', 1, 'event')
            } else if (method === 'calculation') {
                logic.actions.upsertCalculatedMeasure({
                    index: null,
                    name: 'Revenue',
                    expression: 'sum(properties.amount)',
                })
            } else {
                logic.actions.moveFieldToShelf('rows', 0, 'values')
            }
            const updated = logic.values.config
            expect(updated.values).toHaveLength(2)
            expect(updated.values[updated.resultFilters![0].measureIndex]).toMatchObject({
                label: 'Count',
                customExpression: 'count(*)',
            })
            const query = buildBIQuery(updated)!.query
            expect(query).toContain('count(*) AS Count')
            expect(query).toContain('Count > 5')
            expect(parseBIEditorState(BIEditorView.BI, updated)!.config).toEqual(updated)
            logic.unmount()
        }
    )

    it('offers every sidebar table while excluding hidden PostHog tables', () => {
        const biLogic = biEditorLogic({ tabId: TAB_ID })
        biLogic.mount()

        databaseLogic.actions.loadDatabaseSuccess({
            tables: {
                persons: { id: 'persons', name: 'persons', type: 'posthog', fields: {} },
                hidden_table: { id: 'hidden_table', name: 'hidden_table', type: 'posthog', fields: {} },
                events: { id: 'events', name: 'events', type: 'posthog', fields: {} },
                sessions: { id: 'sessions', name: 'sessions', type: 'posthog', fields: {} },
                groups: { id: 'groups', name: 'groups', type: 'posthog', fields: {} },
                custom_orders: { id: 'custom_orders', name: 'custom_orders', type: 'data_warehouse', fields: {} },
                system_metrics: { id: 'system_metrics', name: 'system_metrics', type: 'system', fields: {} },
                revenue_view: {
                    id: 'revenue_view',
                    name: 'revenue_view',
                    type: 'view',
                    fields: {},
                    query: { kind: NodeKind.HogQLQuery, query: 'SELECT 1' },
                },
            },
            joins: [],
        })

        expect(biLogic.values.availableDataSources).toEqual([
            { table: 'custom_orders', connectionId: undefined },
            { table: 'events', connectionId: undefined },
            { table: 'groups', connectionId: undefined },
            { table: 'persons', connectionId: undefined },
            { table: 'revenue_view', connectionId: undefined },
            { table: 'sessions', connectionId: undefined },
            { table: 'system_metrics', connectionId: undefined },
        ])

        biLogic.actions.setDataSource({ table: 'hidden_table' })
        expect(biLogic.values.selectableDataSources[0]).toEqual({ table: 'hidden_table' })
        expect(biLogic.values.selectableDataSources).toHaveLength(biLogic.values.availableDataSources.length + 1)

        biLogic.unmount()
    })

    it('ignores hydration and status from a different connection', async () => {
        await expectLogic(databaseLogic).toFinishAllListeners()
        const biLogic = biEditorLogic({ tabId: TAB_ID })
        biLogic.mount()
        databaseLogic.actions.hydrateTableFieldsFailure(['events'])
        await expectLogic(databaseLogic, () =>
            biLogic.actions.restoreState({
                editorView: BIEditorView.BI,
                config: { ...config, source: { table: 'events', connectionId: 'other-connection' } },
            })
        ).toNotHaveDispatchedActions(['hydrateTableFields'])
        expect(biLogic.values.dataPaneFieldsError).toBe(false)
        databaseLogic.actions.hydrateTableFieldsStart(['events'])
        expect(biLogic.values.dataPaneFieldsLoading).toBe(false)
        biLogic.unmount()
    })

    it('hydrates fields when the schema arrives after restoring a worksheet', async () => {
        await expectLogic(databaseLogic).toFinishAllListeners()
        const biLogic = biEditorLogic({ tabId: TAB_ID })
        biLogic.mount()
        biLogic.actions.restoreState({ editorView: BIEditorView.BI, config })
        expect(biLogic.values.dataPaneFields.dimensions).toEqual([])
        databaseLogic.actions.hydrateTableFieldsFailure(['events'])
        expect(biLogic.values.dataPaneFieldsError).toBe(true)

        queryEndpointMock.mockReturnValue([
            200,
            {
                tables: {
                    events: {
                        id: 'events',
                        name: 'events',
                        type: 'posthog',
                        fields: {
                            event: { name: 'event', type: 'string', schema_valid: true },
                        },
                    },
                },
                joins: [],
            },
        ])
        useMocks({ post: { '/api/environments/:team_id/query/DatabaseSchemaQuery/': queryEndpointMock } })
        databaseLogic.actions.setDatabaseFieldsComplete(false)

        await expectLogic(databaseLogic, () =>
            databaseLogic.actions.loadDatabaseSuccess({
                tables: { events: { id: 'events', name: 'events', type: 'posthog', fields: {} } },
                joins: [],
            })
        ).toDispatchActions(['hydrateTableFieldsSuccess'])

        expect(biLogic.values.dataPaneFields.dimensions).toEqual([
            expect.objectContaining({ name: 'event', expression: 'event' }),
        ])
        expect(biLogic.values.dataPaneFieldsError).toBe(false)
        biLogic.unmount()
    })

    it.each([false, true])(
        'loads connected fields on expansion and keeps their rooted paths (alias=%s)',
        async (alias) => {
            await expectLogic(databaseLogic).toFinishAllListeners()
            const biLogic = biEditorLogic({ tabId: TAB_ID })
            biLogic.mount()
            biLogic.actions.restoreState({ editorView: BIEditorView.BI, config })
            databaseLogic.actions.loadDatabaseSuccess({
                tables: {
                    events: {
                        id: 'events',
                        name: 'events',
                        type: 'posthog',
                        fields: {
                            ...(alias
                                ? {
                                      pdi: {
                                          name: 'pdi',
                                          type: 'lazy_table' as const,
                                          table: 'person_distinct_ids',
                                          hogql_value: 'pdi',
                                          schema_valid: true,
                                      },
                                  }
                                : {}),
                            person: {
                                name: 'person',
                                type: alias ? 'field_traverser' : 'lazy_table',
                                chain: alias ? ['pdi', 'person'] : undefined,
                                table: alias ? undefined : 'persons',
                                hogql_value: 'person',
                                schema_valid: true,
                            },
                        },
                    },
                    persons: { id: 'persons', name: 'persons', type: 'posthog', fields: {} },
                    ...(alias
                        ? {
                              person_distinct_ids: {
                                  id: 'person_distinct_ids',
                                  name: 'person_distinct_ids',
                                  type: 'posthog' as const,
                                  fields: {},
                              },
                          }
                        : {}),
                },
                joins: [],
            })
            databaseLogic.actions.setDatabaseFieldsComplete(false)
            const connections = biConnectionsLogic({ tabId: TAB_ID })
            connections.mount()
            expect(connections.values.connections.find((c) => c.name === 'person')).toMatchObject({
                expanded: false,
                state: 'loading',
            })
            expect(databaseLogic.values.tableFieldsStatus.persons).toBeUndefined()

            queryEndpointMock.mockReturnValue([
                200,
                {
                    tables: {
                        persons: {
                            id: 'persons',
                            name: 'persons',
                            type: 'posthog',
                            fields: {
                                email: { name: 'email', type: 'string', hogql_value: 'email', schema_valid: true },
                            },
                        },
                    },
                    joins: [],
                },
            ])
            if (alias) {
                queryEndpointMock.mockReturnValueOnce([
                    200,
                    {
                        tables: {
                            person_distinct_ids: {
                                id: 'person_distinct_ids',
                                name: 'person_distinct_ids',
                                type: 'posthog',
                                fields: {
                                    person: {
                                        name: 'person',
                                        type: 'lazy_table',
                                        table: 'persons',
                                        hogql_value: 'person',
                                        schema_valid: true,
                                    },
                                },
                            },
                        },
                        joins: [],
                    },
                ])
            }
            useMocks({ post: { '/api/environments/:team_id/query/DatabaseSchemaQuery/': queryEndpointMock } })
            await expectLogic(databaseLogic, () =>
                connections.actions.toggleConnection('["person"]', alias ? 'person_distinct_ids' : 'persons')
            ).toDispatchActions(
                alias ? ['hydrateTableFieldsSuccess', 'hydrateTableFieldsSuccess'] : ['hydrateTableFieldsSuccess']
            )
            expect(connections.values.connections.find((c) => c.name === 'person')!.fields.dimensions).toEqual([
                expect.objectContaining({
                    name: 'person.email',
                    expression: 'person.email',
                    source: config.source,
                }),
            ])
            biLogic.actions.setDataSource({ table: 'persons' })
            expect(connections.values.connections).toEqual([])
            connections.unmount()
            biLogic.unmount()
        }
    )

    it.each(['dimension', 'measure'] as const)(
        'reuses, edits, clears, restores and deletes a worksheet-local %s',
        async (kind) => {
            const logic = biEditorLogic({ tabId: TAB_ID })
            logic.mount()
            logic.actions.restoreState({ editorView: BIEditorView.BI, config })
            const expression = kind === 'dimension' ? "coalesce(properties.plan, 'Unknown')" : 'sum(revenue)'
            const editedExpression = kind === 'dimension' ? 'lower(properties.plan)' : 'avg(revenue)'
            logic.actions.setCalculatedMeasureDraft({ index: null, kind, name: 'Local calculation', expression })
            await expectLogic(logic).toFinishAllListeners()
            logic.actions.saveCalculatedMeasure()
            const field = logic.values.config.localFields![0]
            const shelf = kind === 'dimension' ? 'rows' : 'values'
            logic.actions.duplicateField(shelf, kind === 'dimension' ? logic.values.config.rows.length - 1 : 0)
            if (kind === 'dimension') {
                logic.actions.addFieldToShelf(field, 'filters')
            }
            logic.actions.editCalculatedField(field)
            logic.actions.setCalculatedMeasureDraft({
                ...logic.values.calculatedMeasureDraft!,
                name: 'Renamed calculation',
                expression: editedExpression,
            })
            await expectLogic(logic).toFinishAllListeners()
            logic.actions.saveCalculatedMeasure()
            expect(logic.values.config.localFields![0].name).toBe('Renamed calculation')
            if (kind === 'dimension') {
                expect(logic.values.config.rows.slice(-2).map((field) => field.expression)).toEqual([
                    editedExpression,
                    editedExpression,
                ])
                expect(
                    logic.values.config.filters.find((filter) => filter.field.id === field.id)?.field.expression
                ).toBe(editedExpression)
            } else {
                expect(logic.values.config.values.map((value) => value.customExpression)).toEqual([
                    editedExpression,
                    editedExpression,
                ])
            }
            const saved = parseBIEditorState(BIEditorView.BI, JSON.stringify(logic.values.config))!
            logic.actions.resetConfig()
            expect(logic.values.config.localFields).toEqual(saved.config.localFields)
            expect(
                logic.values.dataPaneFields[kind === 'dimension' ? 'dimensions' : 'measures'].some(
                    (field) => field.name === 'Renamed calculation'
                )
            ).toBe(true)
            logic.actions.restoreState(saved)
            logic.actions.removeLocalField(field.id)
            expect(logic.values.config.localFields).toEqual([])
            expect(logic.values.config.filters.some((filter) => filter.field.id === field.id)).toBe(false)
            expect(logic.values.config.values.some((value) => value.field.id === field.id)).toBe(false)
            expect(logic.values.config.rows.some((row) => (row.localFieldId ?? row.id) === field.id)).toBe(false)
            logic.unmount()
        }
    )

    it('creates and edits a calculated measure without applying canceled drafts or losing its sort', async () => {
        const biLogic = biEditorLogic({ tabId: TAB_ID })
        biLogic.mount()
        biLogic.actions.restoreState({ editorView: BIEditorView.BI, config })
        biLogic.actions.setAutoUpdate(false)
        biLogic.actions.editCalculatedMeasure()
        biLogic.actions.setCalculatedMeasureDraft({
            index: null,
            name: 'ARPU',
            expression: 'sum(revenue) / nullIf(count(DISTINCT user_id), 0)',
        })
        expect(biLogic.values.calculatedMeasureDraft?.name).toBe('ARPU')
        expect(biLogic.values.config.values).toEqual([])
        await expectLogic(biLogic).toFinishAllListeners()
        biLogic.actions.saveCalculatedMeasure()
        expect(biLogic.values.calculatedMeasureDraft).toBeNull()
        expect(biLogic.values.generatedQuery?.query).toContain(
            'sum(revenue) / nullIf(count(DISTINCT user_id), 0) AS ARPU'
        )
        const value = biLogic.values.config.values[0]
        biLogic.actions.setSort({ key: `values:${value.field.id}`, direction: 'asc' })
        biLogic.actions.editCalculatedMeasure(0)
        biLogic.actions.setCalculatedMeasureDraft({ index: 0, name: 'Canceled name', expression: 'avg(revenue)' })
        biLogic.actions.setCalculatedMeasureDraft(null)
        expect(biLogic.values.config.values[0]).toEqual(value)
        biLogic.actions.editCalculatedMeasure(0)
        expect(biLogic.values.calculatedMeasureDraft?.name).toBe('ARPU')
        biLogic.actions.setCalculatedMeasureDraft({ index: 0, name: 'Average revenue', expression: 'avg(revenue)' })
        await expectLogic(biLogic).toFinishAllListeners()
        biLogic.actions.saveCalculatedMeasure()
        expect(biLogic.values.config.values).toHaveLength(1)
        expect(biLogic.values.config.values[0].field.id).toBe(value.field.id)
        expect(biLogic.values.generatedQuery?.query).toContain('avg(revenue) AS "Average revenue"')
        expect(biLogic.values.generatedQuery?.query).toContain('ORDER BY\n    "Average revenue" ASC')
        biLogic.actions.moveFieldToShelf('values', 0, 'filters')
        expect(biLogic.values.config.values).toHaveLength(1)
        expect(biLogic.values.config.filters).toEqual(config.filters)
        biLogic.actions.editCalculatedMeasure(0)
        biLogic.actions.setDataSource({ table: 'other_table' })
        expect(biLogic.values.calculatedMeasureDraft).toBeNull()
        await expectLogic(biLogic).toFinishAllListeners()
        biLogic.actions.saveCalculatedMeasure()
        expect(biLogic.values.config.values).toEqual([])
        biLogic.unmount()
    })

    it('keeps field labels consistent with edited expressions', () => {
        const biLogic = biEditorLogic({ tabId: TAB_ID })
        biLogic.mount()
        biLogic.actions.restoreState({ editorView: BIEditorView.BI, config })
        biLogic.actions.setAutoUpdate(false)
        biLogic.actions.setFieldExpression('rows', 0, 'distinct_id')
        expect(getBIFieldPillLabel(biLogic.values.config.rows[0])).toBe('distinct_id')
        expect(biLogic.values.generatedQuery?.query).toContain('SELECT\n    distinct_id AS distinct_id,')
        biLogic.unmount()
    })
})
