import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { BIConfig, BIField, BIVisualizationNode } from '~/queries/schema/schema-business-intelligence'
import { DatabaseSchemaQuery, HogQLFilters, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { ChartDisplayType, PropertyFilterType, PropertyOperator } from '~/types'

import { claimConnectionScope, releaseConnectionScope } from 'products/data_warehouse/frontend/shared/connectionScope'

import { BI_EDITOR_EVENTS } from './biEditorAnalytics'
import { biEditorLogic } from './biEditorLogic'
import { BIEditorView, buildBIQuery } from './biEditorTypes'
import { biSceneLogic } from './biSceneLogic'

const eventField: BIField = {
    id: 'event',
    name: 'event',
    expression: 'event',
    type: 'string',
    source: { table: 'events' },
}
const timestampField: BIField = {
    id: 'timestamp',
    name: 'timestamp',
    expression: 'timestamp',
    type: 'datetime',
    source: { table: 'events' },
}
const config: BIConfig = {
    source: { table: 'events' },
    dateRange: { date_from: 'all' },
    chartType: ChartDisplayType.ActionsBar,
    rows: [eventField],
    columns: [timestampField],
    values: [],
    filters: [],
    limit: 1000,
    sort: null,
}
const worksheet = (state: BIConfig = config): BIVisualizationNode => ({
    ...buildBIQuery(state)!.node,
    kind: NodeKind.BIVisualizationNode,
    config: state,
})

describe('biSceneLogic', () => {
    let logic: ReturnType<typeof biSceneLogic.build>
    let editor: ReturnType<typeof biEditorLogic.build>
    let stored: { id: number; short_id: string; name: string; query: BIVisualizationNode; user_access_level: string }
    let save: jest.Mock
    let exportedPayload: unknown
    let exportView: jest.Mock

    beforeEach(() => {
        localStorage.clear()
        sessionStorage.clear()
        stored = {
            id: 123,
            short_id: 'bi-test',
            name: 'Saved worksheet',
            query: worksheet(),
            user_access_level: 'editor',
        }
        save = jest.fn(async ({ request }: { request: Request }) => {
            stored = { ...stored, ...(await request.json()) }
            return [200, stored]
        })
        exportView = jest.fn(async ({ request }: { request: Request }) => {
            exportedPayload = await request.json()
            return [200, { id: 'example-view' }]
        })
        useMocks({
            get: {
                '/api/projects/:team_id/insights/': () => [200, { results: [stored] }],
                '/api/projects/:team_id/external_data_sources/connections/': [],
                '/api/projects/:team_id/external_data_sources/direct_connection_options/': [],
                '/api/projects/:team_id/warehouse_saved_queries/': { results: [] },
            },
            post: {
                '/api/environments/:team_id/query/:kind/': async ({ request }) => {
                    const { query } = (await request.json()) as { query: DatabaseSchemaQuery }
                    const name = query.connectionId ? 'orders' : 'events'
                    return [
                        200,
                        {
                            tables: {
                                [name]: {
                                    id: name,
                                    name,
                                    type: query.connectionId ? 'data_warehouse' : 'posthog',
                                    fields:
                                        query.includeFields === false
                                            ? {}
                                            : { event: { name: 'event', type: 'string', schema_valid: true } },
                                },
                            },
                        },
                    ]
                },
                '/api/projects/:team_id/insights/': save,
                '/api/projects/:team_id/insights/viewed/': [201],
                '/api/projects/:team_id/warehouse_saved_queries/': exportView,
            },
            patch: { '/api/projects/:team_id/insights/:id/': save },
            delete: { '/api/environments/:team_id/query/:id/': [204] },
        })
        initKeaTests()
        router.actions.push(urls.businessIntelligenceNew(), {}, { q: '' })
        logic = biSceneLogic({ tabId: 'bi-test' })
        logic.mount()
        editor = biEditorLogic({ tabId: 'bi-test' })
    })
    afterEach(() => logic.unmount())

    it.each([false, true])('protects unsaved worksheet edits when navigating away (saved: %s)', async (saved) => {
        const confirm = jest.spyOn(window, 'confirm').mockReturnValue(false)
        try {
            expect(logic.values.hasUnsavedChanges).toBe(false)
            if (saved) {
                await expectLogic(logic, () =>
                    router.actions.push(urls.businessIntelligenceWorksheet(stored.short_id))
                ).toFinishAllListeners()
            }
            logic.actions.setName('Edited worksheet')
            editor.actions.setDataSource({ table: 'events' })
            await expectLogic(logic).toFinishAllListeners()
            const editorPath = router.values.location.pathname
            expect(confirm).not.toHaveBeenCalled()

            router.actions.push(urls.businessIntelligence())
            expect(confirm).toHaveBeenCalledTimes(1)
            expect(router.values.location.pathname).toBe(editorPath)
            expect(logic.values.name).toBe('Edited worksheet')

            confirm.mockReturnValue(true)
            router.actions.push(urls.businessIntelligence())
            expect(router.values.location.pathname).toBe('/project/997/bi')
            logic.unmount()
            router.actions.push(
                saved ? urls.businessIntelligenceWorksheet(stored.short_id) : urls.businessIntelligenceNew()
            )
            logic = biSceneLogic({ tabId: 'bi-test' })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.name).toBe(saved ? stored.name : 'Untitled worksheet')
            expect(logic.values.hasUnsavedChanges).toBe(false)
        } finally {
            confirm.mockRestore()
        }
    })

    it('waits for Run after selecting a table unless auto update is enabled', async () => {
        editor.actions.setDataSource({ table: 'events' })
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.lastRunQuery).toBeNull()
        logic.actions.runQuery()
        expect(logic.values.lastRunQuery?.source.query).toContain('count(*) AS count')
        logic.actions.setLastRunQuery(null)
        await expectLogic(editor, () => editor.actions.setAutoUpdate(true)).toFinishAllListeners()
        expect(logic.values.lastRunQuery?.source.query).toContain('count(*) AS count')
    })

    it('tracks the first successful chart once, without counting empty results or reruns', async () => {
        const capture = jest.spyOn(posthog, 'capture').mockImplementation()
        logic.actions.restoreWorksheet(worksheet())
        const data = dataNodeLogic({
            key: logic.values.dataNodeKey,
            query: logic.values.worksheet.source,
            autoLoad: false,
        })
        data.mount()
        try {
            data.actions.loadDataSuccess({ results: [], columns: ['count'], types: ['Int64'] })
            expect(capture).not.toHaveBeenCalledWith(
                BI_EDITOR_EVENTS.WORKSHEET_ACTION,
                expect.objectContaining({ action: 'first_chart' })
            )
            data.actions.loadDataSuccess({ results: [[3]], columns: ['count'], types: ['Int64'] })
            data.actions.loadDataSuccess({ results: [[4]], columns: ['count'], types: ['Int64'] })
            expect(
                capture.mock.calls.filter(
                    ([event, properties]) =>
                        event === BI_EDITOR_EVENTS.WORKSHEET_ACTION && properties?.action === 'first_chart'
                )
            ).toHaveLength(1)
        } finally {
            capture.mockRestore()
            data.unmount()
        }
    })

    it.each([false, true])('releases its connection scope without disrupting another owner: %s', async (shared) => {
        const database = databaseTableListLogic()
        database.mount()
        const node = worksheet()
        node.source.connectionId = 'example-connection'
        node.config = { ...node.config, source: { table: 'orders', connectionId: 'example-connection' } }
        if (shared) {
            claimConnectionScope('sql-tab', 'example-connection')
        }
        try {
            logic.actions.restoreWorksheet(node)
            await expectLogic(logic).toFinishAllListeners()
            expect(database.values.connectionId).toBe('example-connection')
            logic.unmount()
            expect(database.values.connectionId).toBe(shared ? 'example-connection' : null)
        } finally {
            releaseConnectionScope('sql-tab', 'example-connection')
            database.unmount()
        }
    })

    it('saves the wrapper and reopens the insight without a draft or SQL editor', async () => {
        const node = worksheet()
        node.chartSettings!.yAxis![0].settings = { formatting: { prefix: '$', suffix: '' } }
        logic.actions.restoreWorksheet(node)
        logic.actions.setName('Revenue worksheet')
        await expectLogic(logic, () => logic.actions.saveInsight()).toFinishAllListeners()
        expect(save).toHaveBeenCalledTimes(1)
        expect(router.values.location.pathname).toBe('/project/997/bi/bi-test')
        expect(stored.query).toMatchObject({ kind: NodeKind.BIVisualizationNode, config })
        expect(stored.query.source).not.toHaveProperty('biConfig')
        logic.unmount()
        localStorage.clear()
        sessionStorage.clear()
        router.actions.push(urls.businessIntelligence({ insightShortId: stored.short_id }))
        logic = biSceneLogic({ tabId: 'reopened' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.worksheet.config).toEqual(config)
        expect(logic.values.worksheet.chartSettings?.yAxis?.[0].settings?.formatting?.prefix).toBe('$')
        expect(logic.values.hasUnsavedChanges).toBe(false)
    })

    it('discards shelf and chart changes while preserving formatting for unchanged columns', async () => {
        stored.query.chartSettings!.yAxis![0].settings = { formatting: { prefix: '$', suffix: '' } }
        await expectLogic(logic, () => logic.actions.loadInsight(stored.short_id)).toFinishAllListeners()
        editor.actions.setChartType(ChartDisplayType.ActionsStackedBar)
        expect(logic.values.hasUnsavedChanges).toBe(true)
        expect(logic.values.worksheet.chartSettings?.yAxis?.[0].settings?.formatting?.prefix).toBe('$')
        editor.actions.setDateRange({ date_from: '-30d' })
        expect(logic.values.worksheet.chartSettings?.yAxis?.[0].settings?.formatting?.prefix).toBe('$')
        logic.actions.discardChanges()
        expect(logic.values.worksheet.config).toEqual(config)
        expect(logic.values.hasUnsavedChanges).toBe(false)
        editor.actions.removeFieldFromShelf('rows', 0)
        expect(logic.values.worksheet.chartSettings?.seriesBreakdownColumn).toBeUndefined()
        expect(logic.values.worksheet.chartSettings?.xAxis).toBeUndefined()
        logic.actions.discardChanges()
        expect(logic.values.worksheet.config).toEqual(config)
    })

    it('exports a plain SQL view and keeps worksheet state in the insight', async () => {
        logic.actions.restoreWorksheet(worksheet())
        logic.actions.setExportViewName('revenue_view')
        await expectLogic(logic, () => logic.actions.exportView()).toFinishAllListeners()
        expect(exportedPayload).toEqual({ name: 'revenue_view', query: JSON.parse(JSON.stringify(worksheet().source)) })
        expect(save).not.toHaveBeenCalled()
    })

    it('undoes shelves, filters, calculations and formatting without running a query, and branches after undo', async () => {
        await expectLogic(logic, () => logic.actions.loadInsight(stored.short_id)).toFinishAllListeners()
        const snapshots = [JSON.parse(JSON.stringify(logic.values.worksheet))]
        const edits = [
            () => editor.actions.addFieldToShelf(eventField, 'filters'),
            () => editor.actions.setFilterValue(0, '$pageview'),
            () => editor.actions.addFieldToShelf(eventField, 'values'),
            () => editor.actions.setTableCalculation(0, { type: 'running_total' }),
            () => editor.actions.updateMeasureSettings(0, { formatting: { prefix: '€' } }),
            () => editor.actions.removeFieldFromShelf('columns', 0),
            () => logic.actions.setVisualization({ ...logic.values.worksheet, chartSettings: { showLegend: false } }),
        ]
        for (const edit of edits) {
            edit()
            snapshots.push(JSON.parse(JSON.stringify(logic.values.worksheet)))
        }
        const lastRun = logic.values.lastRunQuery
        for (let index = snapshots.length - 2; index >= 0; index--) {
            logic.actions.undo()
            expect(JSON.parse(JSON.stringify(logic.values.worksheet))).toEqual(snapshots[index])
            expect(logic.values.lastRunQuery).toEqual(lastRun)
        }
        expect(logic.values.canUndo).toBe(false)
        for (const snapshot of snapshots.slice(1)) {
            logic.actions.redo()
            expect(JSON.parse(JSON.stringify(logic.values.worksheet))).toEqual(snapshot)
        }
        expect(logic.values.canRedo).toBe(false)
        logic.actions.undo()
        editor.actions.setLimit(100)
        expect(logic.values.canRedo).toBe(false)
        logic.actions.discardChanges()
        expect(logic.values.canUndo).toBe(false)
        expect(logic.values.hasUnsavedChanges).toBe(false)
    })

    it('runs the restored worksheet when auto update is enabled', async () => {
        await expectLogic(logic, () => logic.actions.loadInsight(stored.short_id)).toFinishAllListeners()
        await expectLogic(editor, () => editor.actions.setAutoUpdate(true)).toFinishAllListeners()
        await expectLogic(editor, () => editor.actions.setLimit(100)).toFinishAllListeners()
        expect(logic.values.lastRunQuery?.config.limit).toBe(100)
        await expectLogic(logic, () => logic.actions.undo()).toFinishAllListeners()
        expect(logic.values.lastRunQuery?.config.limit).toBe(config.limit)
    })

    it('creates a separate worksheet copy and preserves the original, including after a failed copy', async () => {
        await expectLogic(logic, () => logic.actions.loadInsight(stored.short_id)).toFinishAllListeners()
        const original = JSON.parse(JSON.stringify(stored))
        let fail = true
        let copy: unknown
        const createCopy = jest.fn(async ({ request }: { request: Request }) => {
            const payload = await request.json()
            copy = { ...payload, id: 456, short_id: 'copy' }
            return fail ? [500, { detail: 'Could not save copy' }] : [201, copy]
        })
        useMocks({
            post: { '/api/projects/:team_id/insights/': createCopy },
            get: { '/api/projects/:team_id/insights/': () => [200, { results: [copy] }] },
        })
        editor.actions.setLimit(100)
        await expectLogic(logic, () => logic.actions.saveInsight({ asCopy: true })).toFinishAllListeners()
        expect(logic.values.insight?.id).toBe(original.id)
        expect(logic.values.insightLoading).toBe(false)
        expect(logic.values.worksheet.config.limit).toBe(100)
        fail = false
        await expectLogic(logic, () => logic.actions.saveInsight({ asCopy: true })).toFinishAllListeners()
        expect(save).not.toHaveBeenCalled()
        expect(stored).toEqual(original)
        expect(createCopy).toHaveBeenCalledTimes(2)
        expect(router.values.location.pathname).toBe('/project/997/bi/copy')
        expect(logic.values.insight?.name).toBe('Saved worksheet (copy)')
    })

    it('preserves an unfinished calculated measure when chart settings update', () => {
        logic.actions.restoreWorksheet(worksheet())
        editor.actions.setCalculatedMeasureDraft({
            index: null,
            name: 'Revenue per user',
            expression: 'sum(revenue) /',
        })
        const draft = editor.values.calculatedMeasureDraft
        logic.actions.setVisualization({ ...logic.values.worksheet, tableSettings: { conditionalFormatting: [] } })
        expect(editor.values.calculatedMeasureDraft).toEqual(draft)
    })

    it('reruns unchanged SQL for a date change while preserving dashboard properties', async () => {
        const properties: HogQLFilters['properties'] = [
            { type: PropertyFilterType.Event, key: 'plan', value: 'pro', operator: PropertyOperator.Exact },
        ]
        const node = worksheet()
        node.source.filters = { dateRange: { date_from: '-7d' }, properties }
        logic.actions.restoreWorksheet(node)
        expect(editor.values.config.dateRange).toEqual({ date_from: '-7d' })
        const sql = logic.values.worksheet.source.query
        const data = dataNodeLogic({ key: logic.values.dataNodeKey, query: node.source, autoLoad: false })
        data.mount()
        data.actions.setResponse({ results: [[1]], columns: ['count'], types: [['count', 'Int64']] })
        jest.useFakeTimers()
        try {
            editor.actions.setAutoUpdate(true)
            editor.actions.setDateRange({ date_from: '-30d' })
            await jest.advanceTimersByTimeAsync(500)
            expect(logic.values.lastRunQuery?.source.query).toBe(sql)
            expect(logic.values.lastRunQuery?.source.filters).toEqual({ dateRange: { date_from: '-30d' }, properties })
        } finally {
            jest.useRealTimers()
            data.unmount()
        }
    })

    it('restores legacy BI links and persists edits as a wrapper', async () => {
        router.actions.push(urls.businessIntelligence(), {}, { q: 'SELECT event FROM events', bi: config, mode: 'bi' })
        await expectLogic(databaseTableListLogic).toFinishAllListeners()
        expect(editor.values.dataPaneFields.dimensions.map((field) => field.name)).toContain('event')
        expect(logic.values.config).toEqual(config)
        editor.actions.setFieldDateBucket('columns', 0, 'day')
        editor.actions.setLimit(50000)
        expect(logic.values.worksheet.source.query).toContain('toStartOfDay(timestamp)')
        expect(logic.values.worksheet.source.query).toContain('LIMIT 50000')
        expect(JSON.parse(router.values.hashParams.q).config).toEqual(logic.values.config)
        logic.unmount()
        router.actions.push(urls.businessIntelligence())
        logic = biSceneLogic({ tabId: 'bi-test' })
        logic.mount()
        expect(logic.values.config.limit).toBe(50000)
    })

    it('resets fields and results when switching connections', async () => {
        logic.actions.restoreWorksheet(worksheet())
        logic.actions.selectConnection('example-connection')
        expect(logic.values.config.source).toBeNull()
        expect(logic.values.config.rows).toEqual([])
        expect(logic.values.lastRunQuery).toBeNull()
        expect(databaseTableListLogic.values.connectionId).toBe('example-connection')
        editor.actions.setDataSource({ table: 'orders', connectionId: 'example-connection' })
        await expectLogic(databaseTableListLogic).toFinishAllListeners()
        expect(editor.values.dataPaneFields.dimensions.map((field) => field.name)).toContain('event')
        expect(logic.values.worksheet.source.connectionId).toBe('example-connection')
    })

    test.each(['ready', 'failed', 'cancelled', 'missing'] as const)(
        'handles chart-only edits with %s results',
        async (state) => {
            logic.actions.restoreWorksheet(worksheet())
            const data = dataNodeLogic({
                key: logic.values.dataNodeKey,
                query: logic.values.worksheet.source,
                autoLoad: false,
            })
            data.mount()
            if (state !== 'missing') {
                data.actions.setResponse({ results: [[1]], columns: ['1'], types: ['Int64'] })
            }
            if (state === 'failed') {
                data.actions.loadDataFailure('Query failed', { detail: 'Query failed' })
            }
            if (state === 'cancelled') {
                data.actions.cancelQuery()
            }
            const run = jest.spyOn(logic.actions, 'runQuery')
            jest.useFakeTimers()
            try {
                editor.actions.setAutoUpdate(true)
                editor.actions.setChartType(ChartDisplayType.ActionsStackedBar)
                await jest.advanceTimersByTimeAsync(500)
                expect(run).toHaveBeenCalledTimes(state === 'ready' ? 0 : 1)
                editor.actions.setChartType(ChartDisplayType.ActionsTable)
                await jest.advanceTimersByTimeAsync(500)
                expect(run).toHaveBeenCalledTimes(state === 'ready' ? 1 : 2)
            } finally {
                jest.useRealTimers()
                data.unmount()
                run.mockRestore()
            }
        }
    )

    test.each(['disable', 'clear', 'invalid', 'unchanged'] as const)(
        'handles pending auto-update when %s',
        async (transition) => {
            logic.actions.restoreWorksheet(worksheet())
            const run = jest.spyOn(logic.actions, 'runQuery')
            jest.useFakeTimers()
            try {
                editor.actions.setAutoUpdate(true)
                editor.actions.setLimit(10000)
                if (transition === 'disable') {
                    editor.actions.setAutoUpdate(false)
                }
                if (transition === 'clear') {
                    editor.actions.resetConfig()
                }
                if (transition === 'invalid') {
                    editor.actions.restoreState({
                        editorView: BIEditorView.BI,
                        config: {
                            ...config,
                            filters: [
                                {
                                    field: { ...eventField, type: 'integer' },
                                    operator: 'between',
                                    value: '0',
                                    valueTo: 'abc',
                                },
                            ],
                        },
                    })
                    editor.actions.setLimit(10000)
                }
                await jest.advanceTimersByTimeAsync(500)
                expect(run).toHaveBeenCalledTimes(transition === 'unchanged' ? 1 : 0)
            } finally {
                jest.useRealTimers()
                run.mockRestore()
            }
        }
    )

    it('clears cached results when clearing the worksheet', async () => {
        logic.actions.restoreWorksheet(worksheet())
        const data = dataNodeLogic({
            key: logic.values.dataNodeKey,
            query: logic.values.worksheet.source,
            autoLoad: false,
        })
        data.mount()
        data.actions.setResponse({ results: [[1]], columns: ['1'], types: ['Int64'] })
        await expectLogic(editor, () => editor.actions.resetConfig()).toFinishAllListeners()
        expect(data.values.response).toBeNull()
        expect(data.values.queryCancelled).toBe(false)
        expect(logic.values.lastRunQuery).toBeNull()
        data.unmount()
    })
})
