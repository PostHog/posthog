import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'

import { useMocks } from '~/mocks/jest'
import { BIConfig, BIField } from '~/queries/schema/schema-business-intelligence'
import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { ChartDisplayType } from '~/types'

import { biConnectionsLogic } from './biConnectionsLogic'
import { biEditorLogic } from './biEditorLogic'
import { BIEditorView, buildBIQuery, getBIFieldPillLabel, parseBIEditorState } from './biEditorTypes'

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
            post: { '/api/environments/:team_id/query/': queryEndpointMock },
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
    it.each([0, 1, 2])('keeps Top N and result filters attached to their measures when removing value %s', (index) => {
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
        logic.actions.removeFieldFromShelf('values', index)
        expect(logic.values.config.resultFilters).toHaveLength(2)
        for (const filter of logic.values.config.resultFilters!) {
            expect(logic.values.config.values[filter.measureIndex].field.id).toBe(
                filter.id.replace('filter-', 'measure-')
            )
        }
        if (index === 1) {
            expect(logic.values.config.topN).toBeUndefined()
        } else {
            const measureIndex = logic.values.config.topN!.measureIndex
            expect(logic.values.config.values[measureIndex].field.id).toBe('measure-1')
        }
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

    it('creates and edits a calculated measure without applying canceled drafts or losing its sort', () => {
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
        expect(biLogic.values.generatedQuery?.query).toContain('SELECT\n    distinct_id,')
        biLogic.unmount()
    })
})
