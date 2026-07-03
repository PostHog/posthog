import { router } from 'kea-router'
import { expectLogic, partial } from 'kea-test-utils'

import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'
import { dataWarehouseViewsLogic } from 'scenes/data-warehouse/saved_queries/dataWarehouseViewsLogic'
import { insightsApi } from 'scenes/insights/utils/api'
import { sceneLogic } from 'scenes/sceneLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { dataVisualizationLogic } from '~/queries/nodes/DataVisualization/dataVisualizationLogic'
import * as queryRunner from '~/queries/query'
import {
    DataTableNode,
    DataVisualizationNode,
    HogQLFilters,
    HogQLQuery,
    NodeKind,
} from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { ChartDisplayType, InsightShortId, QueryBasedInsightModel } from '~/types'

import { editorSceneLogic } from './editorSceneLogic'
import { OutputTab } from './outputPaneLogic'
import { activeTabMatchesUrlTarget, getDisplayTypeToSaveInsight, sqlEditorLogic } from './sqlEditorLogic'

// endpointLogic uses permanentlyMount() with a keyed logic, which crashes in
// tests without the full React component tree — disable auto-mounting
jest.mock('lib/utils/kea-logic-builders', () => ({
    permanentlyMount: () => () => {},
}))

const MOCK_INSIGHT_SHORT_ID = 'abc123' as InsightShortId

const MOCK_INSIGHT_QUERY: DataVisualizationNode = {
    kind: NodeKind.DataVisualizationNode,
    source: {
        kind: NodeKind.HogQLQuery,
        query: 'SELECT count() FROM events',
    },
}

const MOCK_DATA_TABLE_INSIGHT_SHORT_ID = 'def456' as InsightShortId

const MOCK_DATA_TABLE_INSIGHT_QUERY: DataTableNode = {
    kind: NodeKind.DataTableNode,
    source: {
        kind: NodeKind.HogQLQuery,
        query: 'SELECT count() FROM persons',
    },
}

const MOCK_DATA_TABLE_INSIGHT: QueryBasedInsightModel = {
    id: 2,
    short_id: MOCK_DATA_TABLE_INSIGHT_SHORT_ID,
    name: 'DataTable Insight',
    query: MOCK_DATA_TABLE_INSIGHT_QUERY,
    result: null,
    dashboards: [],
    dashboard_tiles: [],
    saved: true,
    order: null,
    last_refresh: null,
    created_at: '2024-01-01T00:00:00.000Z',
    created_by: null,
    deleted: false,
    description: '',
    is_sample: false,
    is_shared: null,
    pinned: null,
    refresh_interval: null,
    updated_at: '2024-01-01T00:00:00.000Z',
    updated_by: null,
    visibility: null,
    last_modified_at: '2024-01-01T00:00:00.000Z',
    last_modified_by: null,
    layouts: {},
    color: null,
    user_access_level: 'none',
} as QueryBasedInsightModel

const MOCK_INSIGHT: QueryBasedInsightModel = {
    id: 1,
    short_id: MOCK_INSIGHT_SHORT_ID,
    name: 'Test Insight',
    query: MOCK_INSIGHT_QUERY,
    result: null,
    dashboards: [],
    dashboard_tiles: [],
    saved: true,
    order: null,
    last_refresh: null,
    created_at: '2024-01-01T00:00:00.000Z',
    created_by: null,
    deleted: false,
    description: '',
    is_sample: false,
    is_shared: null,
    pinned: null,
    refresh_interval: null,
    updated_at: '2024-01-01T00:00:00.000Z',
    updated_by: null,
    visibility: null,
    last_modified_at: '2024-01-01T00:00:00.000Z',
    last_modified_by: null,
    layouts: {},
    color: null,
    user_access_level: 'none',
} as QueryBasedInsightModel

const MOCK_VIEW = {
    id: 'test-view',
    name: 'Test view',
    query: {
        kind: NodeKind.HogQLQuery,
        query: 'SELECT 1',
    },
    is_materialized: false,
    latest_history_id: null,
    sync_frequency: null,
    status: null,
    last_run_at: null,
    latest_error: null,
} as any

const MOCK_DRAFT = {
    id: 'test-draft',
    name: 'Test draft',
    query: {
        kind: NodeKind.HogQLQuery,
        query: 'SELECT 2',
    },
    saved_query_id: MOCK_VIEW.id,
} as any

function createMockMonaco(): any {
    const mockModel = {
        getValue: () => '',
        setValue: jest.fn(),
        onDidChangeContent: jest.fn(() => ({ dispose: jest.fn() })),
        dispose: jest.fn(),
    }

    return {
        Uri: {
            parse: (uri: string) => ({ toString: () => uri, path: uri }),
        },
        editor: {
            getModel: () => null,
            createModel: () => mockModel,
        },
    }
}

function createMockEditor(): any {
    return {
        setModel: jest.fn(),
        focus: jest.fn(),
        getModel: () => null,
    }
}

describe('sqlEditorLogic', () => {
    let logic: ReturnType<typeof sqlEditorLogic.build>
    let editorRootLogic: ReturnType<typeof editorSceneLogic.build> | undefined
    let databaseLogic: ReturnType<typeof databaseTableListLogic.build>
    const TAB_ID = '1'
    let queryEndpointMock: jest.Mock
    let materializeEndpointMock: jest.Mock

    beforeEach(async () => {
        queryEndpointMock = jest.fn(() => [200, { tables: {}, joins: [] }])
        materializeEndpointMock = jest.fn(() => [200, {}])
        useMocks({
            get: {
                '/api/environments/:team_id/insights/': ({ request }) => {
                    const shortId = new URL(request.url).searchParams.get('short_id')
                    if (shortId === MOCK_INSIGHT_SHORT_ID) {
                        return [200, { results: [MOCK_INSIGHT] }]
                    }
                    if (shortId === MOCK_DATA_TABLE_INSIGHT_SHORT_ID) {
                        return [200, { results: [MOCK_DATA_TABLE_INSIGHT] }]
                    }
                    return [200, { results: [] }]
                },
                '/api/environments/:team_id/warehouse_saved_queries/': { results: [MOCK_VIEW] },
                '/api/environments/:team_id/warehouse_saved_queries/:id/': ({ params }) => {
                    if (params.id === MOCK_VIEW.id) {
                        return [200, MOCK_VIEW]
                    }
                    return [404]
                },
                '/api/environments/:team_id/data_modeling_dags/': { results: [] },
                '/api/environments/:team_id/data_modeling_nodes/': { results: [] },
                '/api/environments/:team_id/data_modeling_edges/': { results: [] },
                '/api/environments/:team_id/data_modeling_jobs/recent/': [],
                '/api/environments/:team_id/data_modeling_jobs/running/': [],
                '/api/environments/:team_id/lineage/get_upstream/': { nodes: [], edges: [] },
                '/api/user_home_settings/@me/': {},
            },
            post: {
                '/api/environments/:team_id/query/': queryEndpointMock,
                '/api/environments/:team_id/warehouse_saved_queries/': () => [
                    200,
                    {
                        id: 'created-view-id',
                        name: 'Materialized view',
                        query: { kind: NodeKind.HogQLQuery, query: 'SELECT 1' },
                        is_materialized: false,
                        latest_history_id: null,
                        sync_frequency: null,
                        status: null,
                        last_run_at: null,
                        latest_error: null,
                    },
                ],
                '/api/environments/:team_id/warehouse_saved_queries/:id/materialize/': materializeEndpointMock,
            },
            patch: {
                '/api/user_home_settings/@me/': [200],
            },
            delete: {
                '/api/environments/:team_id/query/:id/': [204],
            },
        })

        initKeaTests()
        teamLogic.mount()
        sceneLogic.mount()
        databaseLogic = databaseTableListLogic()
        databaseLogic.mount()
        await expectLogic(teamLogic).toFinishAllListeners()
    })

    afterEach(() => {
        editorRootLogic?.unmount()
        editorRootLogic = undefined
        logic?.unmount()
        databaseLogic?.unmount()
    })

    it('keeps configured filters when the filters placeholder is removed from the query text', () => {
        logic = sqlEditorLogic({
            tabId: TAB_ID,
            monaco: createMockMonaco(),
            editor: createMockEditor(),
        })
        logic.mount()

        logic.actions.setSourceQuery({
            kind: NodeKind.DataVisualizationNode,
            source: {
                kind: NodeKind.HogQLQuery,
                query: 'SELECT * FROM events WHERE {filters}',
                filters: {
                    filterTestAccounts: true,
                },
            },
            display: ChartDisplayType.Auto,
        })
        logic.actions.setQueryInput('SELECT * FROM events WHERE {filters}')

        logic.actions.setQueryInput('SELECT * FROM events')

        expect((logic.values.sourceQuery.source as HogQLQuery).filters).toEqual({
            filterTestAccounts: true,
        })
    })

    it('does not count a commented filters placeholder as active', () => {
        logic = sqlEditorLogic({
            tabId: TAB_ID,
            monaco: createMockMonaco(),
            editor: createMockEditor(),
        })
        logic.mount()

        logic.actions.setQueryInput('SELECT * FROM events\n-- WHERE {filters}')

        expect(logic.values.hasFiltersPlaceholder).toBe(false)
    })

    it('restores filters from the URL hash', async () => {
        const filters: HogQLFilters = {
            dateRange: {
                date_from: '-7d',
                date_to: null,
            },
            filterTestAccounts: true,
        }

        logic = sqlEditorLogic({
            tabId: TAB_ID,
            monaco: createMockMonaco(),
            editor: createMockEditor(),
        })
        logic.mount()

        router.actions.push(urls.sqlEditor(), undefined, {
            q: 'SELECT * FROM events WHERE {filters}',
            filters,
        })

        await expectLogic(logic)
            .toDispatchActions(['setSourceQuery', 'createTab', 'updateTab'])
            .toMatchValues({
                sourceQuery: partial({
                    source: partial({
                        filters,
                    }),
                }),
            })
    })

    it('syncs filters to the URL hash and removes them after reset', async () => {
        const filters: HogQLFilters = {
            dateRange: {
                date_from: '-30d',
                date_to: null,
            },
            filterTestAccounts: true,
        }

        logic = sqlEditorLogic({
            tabId: TAB_ID,
            monaco: createMockMonaco(),
            editor: createMockEditor(),
        })
        logic.mount()

        logic.actions.createTab('SELECT * FROM events WHERE {filters}')
        await expectLogic(logic).toDispatchActions(['createTab', 'updateTab'])

        logic.actions.setSourceQuery({
            ...logic.values.sourceQuery,
            source: {
                ...logic.values.sourceQuery.source,
                filters,
            },
        })
        await new Promise((resolve) => setTimeout(resolve, 0))

        expect(router.values.hashParams.filters).toEqual(filters)

        logic.actions.setSourceQuery({
            ...logic.values.sourceQuery,
            source: {
                ...logic.values.sourceQuery.source,
                filters: {},
            },
        })
        await new Promise((resolve) => setTimeout(resolve, 0))

        expect(router.values.hashParams.filters).toBeUndefined()
    })

    it('syncs filters to the URL hash when the query is empty', async () => {
        const filters: HogQLFilters = {
            filterTestAccounts: true,
        }

        logic = sqlEditorLogic({
            tabId: TAB_ID,
            monaco: createMockMonaco(),
            editor: createMockEditor(),
        })
        logic.mount()

        logic.actions.createTab()
        await expectLogic(logic).toDispatchActions(['createTab', 'updateTab'])

        expect(logic.values.queryInput).toBeNull()

        logic.actions.setSourceQuery({
            ...logic.values.sourceQuery,
            source: {
                ...logic.values.sourceQuery.source,
                filters,
            },
        })
        await new Promise((resolve) => setTimeout(resolve, 0))

        expect(router.values.hashParams.filters).toEqual(filters)
    })

    describe('title section', () => {
        it('shows loading view title when opening a view from URL before view loads', async () => {
            logic = sqlEditorLogic({
                tabId: TAB_ID,
                monaco: createMockMonaco(),
                editor: createMockEditor(),
            })
            logic.mount()
            editorRootLogic = editorSceneLogic({ tabId: TAB_ID })
            editorRootLogic.mount()

            window.history.replaceState({}, '', `${urls.sqlEditor()}?open_view=test-view`)

            expect(editorRootLogic.values.titleSectionProps.name).toEqual('Loading view...')
        })

        it('shows loading insight title when opening an insight from URL before insight loads', async () => {
            logic = sqlEditorLogic({
                tabId: TAB_ID,
                monaco: createMockMonaco(),
                editor: createMockEditor(),
            })
            logic.mount()
            editorRootLogic = editorSceneLogic({ tabId: TAB_ID })
            editorRootLogic.mount()

            window.history.replaceState({}, '', `${urls.sqlEditor()}?open_insight=${MOCK_INSIGHT_SHORT_ID}`)

            expect(editorRootLogic.values.titleSectionProps.name).toEqual('Loading insight...')
        })

        it('closes an insight into an unsaved query without clearing SQL or visualization settings', async () => {
            logic = sqlEditorLogic({
                tabId: TAB_ID,
                monaco: createMockMonaco(),
                editor: createMockEditor(),
            })
            logic.mount()
            editorRootLogic = editorSceneLogic({ tabId: TAB_ID })
            editorRootLogic.mount()

            window.history.replaceState(
                {},
                '',
                `${urls.sqlEditor()}?open_insight=${MOCK_INSIGHT.short_id}#${JSON.stringify({ insight: MOCK_INSIGHT.short_id })}`
            )
            logic.actions.createTab(MOCK_INSIGHT_QUERY.source.query, undefined, MOCK_INSIGHT)
            await expectLogic(logic).toDispatchActions(['createTab', 'updateTab'])

            logic.actions.setSourceQuery({
                ...MOCK_INSIGHT_QUERY,
                display: ChartDisplayType.BoldNumber,
            })
            logic.actions.setInsightLoading(true)
            logic.actions.closeEditingObject()

            await expectLogic(logic)
                .toDispatchActions(['closeEditingObject', 'setInsightLoading', 'setViewLoading', 'updateTab'])
                .toMatchValues({
                    editingInsight: null,
                    insightLoading: false,
                    queryInput: MOCK_INSIGHT_QUERY.source.query,
                    sourceQuery: partial({
                        display: ChartDisplayType.BoldNumber,
                    }),
                })

            expect(editorRootLogic.values.titleSectionProps).toMatchObject({
                name: 'New SQL query',
            })
            expect(window.location.hash).not.toContain('insight')
            expect(window.location.search).not.toContain('open_insight')
        })

        it('closes a view into an unsaved query without clearing SQL or visualization settings', async () => {
            logic = sqlEditorLogic({
                tabId: TAB_ID,
                monaco: createMockMonaco(),
                editor: createMockEditor(),
            })
            logic.mount()
            editorRootLogic = editorSceneLogic({ tabId: TAB_ID })
            editorRootLogic.mount()

            window.history.replaceState(
                {},
                '',
                `${urls.sqlEditor()}?open_view=${MOCK_VIEW.id}#${JSON.stringify({ view: MOCK_VIEW.id })}`
            )
            logic.actions.createTab(MOCK_VIEW.query.query, MOCK_VIEW)
            await expectLogic(logic).toDispatchActions(['createTab', 'updateTab'])

            logic.actions.setSourceQuery({
                kind: NodeKind.DataVisualizationNode,
                source: {
                    kind: NodeKind.HogQLQuery,
                    query: MOCK_VIEW.query.query,
                },
                display: ChartDisplayType.ActionsBar,
            })
            logic.actions.setViewLoading(true)
            logic.actions.closeEditingObject()

            await expectLogic(logic)
                .toDispatchActions(['closeEditingObject', 'setInsightLoading', 'setViewLoading', 'updateTab'])
                .toMatchValues({
                    editingView: undefined,
                    viewLoading: false,
                    queryInput: MOCK_VIEW.query.query,
                    sourceQuery: partial({
                        display: ChartDisplayType.ActionsBar,
                    }),
                })

            expect(editorRootLogic.values.titleSectionProps).toMatchObject({
                name: 'New SQL query',
            })
            expect(window.location.hash).not.toContain('view')
            expect(window.location.search).not.toContain('open_view')
        })
    })

    describe('beforeUnmount disposes tracked Monaco models', () => {
        function createTrackedModel(): { model: any; dispose: jest.Mock } {
            const dispose = jest.fn()
            const model = {
                dispose,
                isDisposed: () => false,
                codeEditorLogic: { sentinel: true },
            }
            return { model, dispose }
        }

        it('clears codeEditorLogic and calls dispose on every tracked model when the logic unmounts', () => {
            logic = sqlEditorLogic({
                tabId: TAB_ID,
                monaco: createMockMonaco(),
                editor: createMockEditor(),
            })
            logic.mount()

            const tracked = [createTrackedModel(), createTrackedModel()]
            logic.cache.createdModels = tracked.map((t) => t.model)

            logic.unmount()
            logic = undefined as any

            for (const { model, dispose } of tracked) {
                expect(model.codeEditorLogic).toBeUndefined()
                expect(dispose).toHaveBeenCalledTimes(1)
            }
        })

        it('clears codeEditorLogic even when model.dispose throws', () => {
            logic = sqlEditorLogic({
                tabId: TAB_ID,
                monaco: createMockMonaco(),
                editor: createMockEditor(),
            })
            logic.mount()

            const dispose = jest.fn(() => {
                throw new Error('already disposed')
            })
            const model: any = {
                dispose,
                isDisposed: () => false,
                codeEditorLogic: { sentinel: true },
            }
            logic.cache.createdModels = [model]

            logic.unmount()
            logic = undefined as any

            expect(model.codeEditorLogic).toBeUndefined()
            expect(dispose).toHaveBeenCalledTimes(1)
        })
    })

    describe('getDisplayTypeToSaveInsight', () => {
        it.each([
            {
                name: 'saves table when results tab is selected',
                outputTab: OutputTab.Results,
                sourceQueryDisplay: ChartDisplayType.Auto,
                effectiveVisualizationType: ChartDisplayType.ActionsBar,
                expected: ChartDisplayType.ActionsTable,
            },
            {
                name: 'saves explicit display from source query when not auto',
                outputTab: OutputTab.Visualization,
                sourceQueryDisplay: ChartDisplayType.ActionsAreaGraph,
                effectiveVisualizationType: ChartDisplayType.ActionsBar,
                expected: ChartDisplayType.ActionsAreaGraph,
            },
            {
                name: 'saves effective visualization when source query is auto',
                outputTab: OutputTab.Visualization,
                sourceQueryDisplay: ChartDisplayType.Auto,
                effectiveVisualizationType: ChartDisplayType.BoldNumber,
                expected: ChartDisplayType.BoldNumber,
            },
            {
                name: 'saves visualization when both outputs are selected',
                outputTab: OutputTab.Both,
                sourceQueryDisplay: ChartDisplayType.Auto,
                effectiveVisualizationType: ChartDisplayType.BoldNumber,
                expected: ChartDisplayType.BoldNumber,
            },
            {
                name: 'falls back to line graph when there is no effective visualization',
                outputTab: OutputTab.Visualization,
                sourceQueryDisplay: ChartDisplayType.Auto,
                effectiveVisualizationType: undefined,
                expected: ChartDisplayType.ActionsLineGraph,
            },
        ])('$name', ({ outputTab, sourceQueryDisplay, effectiveVisualizationType, expected }) => {
            expect(getDisplayTypeToSaveInsight(outputTab, sourceQueryDisplay, effectiveVisualizationType)).toEqual(
                expected
            )
        })
    })

    describe('open_insight URL parameter', () => {
        it('sets editingInsight when opening an insight via open_insight search param', async () => {
            logic = sqlEditorLogic({
                tabId: TAB_ID,
                monaco: createMockMonaco(),
                editor: createMockEditor(),
            })
            logic.mount()

            router.actions.push(urls.sqlEditor(), { open_insight: MOCK_INSIGHT_SHORT_ID })

            await expectLogic(logic)
                .toDispatchActions(['editInsight', 'createTab', 'updateTab'])
                .toMatchValues({
                    editingInsight: partial({
                        short_id: MOCK_INSIGHT_SHORT_ID,
                    }),
                })
        })

        it('sets insightLoading to false after insight finishes loading', async () => {
            logic = sqlEditorLogic({
                tabId: TAB_ID,
                monaco: createMockMonaco(),
                editor: createMockEditor(),
            })
            logic.mount()

            router.actions.push(urls.sqlEditor(), { open_insight: MOCK_INSIGHT_SHORT_ID })

            await expectLogic(logic).toDispatchActions(['editInsight', 'createTab', 'updateTab']).toMatchValues({
                insightLoading: false,
            })
        })

        it('preserves editingInsight when reopening after starting from a new SQL tab', async () => {
            logic = sqlEditorLogic({
                tabId: TAB_ID,
                monaco: createMockMonaco(),
                editor: createMockEditor(),
            })
            logic.mount()
            editorRootLogic = editorSceneLogic({ tabId: TAB_ID })
            editorRootLogic.mount()

            logic.actions.createTab('SELECT 1')
            await expectLogic(logic).toDispatchActions(['createTab', 'updateTab'])

            router.actions.push(urls.sqlEditor(), { open_insight: MOCK_INSIGHT_SHORT_ID })

            await expectLogic(logic)
                .toDispatchActions(['editInsight', 'createTab', 'updateTab'])
                .toMatchValues({
                    editingInsight: partial({
                        short_id: MOCK_INSIGHT_SHORT_ID,
                    }),
                })
        })

        it('wraps a DataTableNode insight into a DataVisualizationNode so saves do not fail', async () => {
            logic = sqlEditorLogic({
                tabId: TAB_ID,
                monaco: createMockMonaco(),
                editor: createMockEditor(),
            })
            logic.mount()
            editorRootLogic = editorSceneLogic({ tabId: TAB_ID })
            editorRootLogic.mount()

            router.actions.push(urls.sqlEditor(), { open_insight: MOCK_DATA_TABLE_INSIGHT_SHORT_ID })

            await expectLogic(logic)
                .toDispatchActions(['editInsight', 'createTab', 'updateTab'])
                .toMatchValues({
                    editingInsight: partial({
                        short_id: MOCK_DATA_TABLE_INSIGHT_SHORT_ID,
                    }),
                    sourceQuery: partial({
                        kind: NodeKind.DataVisualizationNode,
                        source: partial({
                            kind: NodeKind.HogQLQuery,
                            query: (MOCK_DATA_TABLE_INSIGHT_QUERY.source as HogQLQuery).query,
                        }),
                    }),
                })

            // The button should not appear "dirty" immediately after load
            expect(editorRootLogic.values.updateInsightButtonEnabled).toEqual(false)
        })

        it('enables Update insight as soon as sourceQuery diverges from the saved insight, even when dataVisualizationLogic mirror lags behind', async () => {
            logic = sqlEditorLogic({
                tabId: TAB_ID,
                monaco: createMockMonaco(),
                editor: createMockEditor(),
            })
            logic.mount()
            editorRootLogic = editorSceneLogic({ tabId: TAB_ID })
            editorRootLogic.mount()

            router.actions.push(urls.sqlEditor(), { open_insight: MOCK_INSIGHT_SHORT_ID })

            await expectLogic(logic)
                .toDispatchActions(['editInsight', 'createTab', 'updateTab'])
                .toMatchValues({
                    editingInsight: partial({ short_id: MOCK_INSIGHT_SHORT_ID }),
                })

            // Mount dataVisualizationLogic with the saved query, mirroring what BindLogic
            // does in production. This is the state right after the insight finishes loading.
            const dataLogicKey = logic.values.dataLogicKey
            const visualizationLogic = dataVisualizationLogic({
                key: dataLogicKey,
                query: MOCK_INSIGHT_QUERY,
                dataNodeCollectionId: dataLogicKey,
            })
            visualizationLogic.mount()

            expect(editorRootLogic.values.updateInsightButtonEnabled).toEqual(false)

            // Simulate runQuery firing setSourceQuery with a different SQL string.
            // dataVisualizationLogic.values.query still mirrors the OLD query at this point —
            // in production it only catches up after React re-renders and propsChanged fires.
            // The selector must reflect the change immediately so the user can save.
            logic.actions.setSourceQuery({
                ...MOCK_INSIGHT_QUERY,
                source: { ...MOCK_INSIGHT_QUERY.source, query: 'SELECT count() FROM events WHERE event = $pageview' },
            })

            expect(editorRootLogic.values.updateInsightButtonEnabled).toEqual(true)

            visualizationLogic.unmount()
        })

        it('does not dispatch syncUrlWithQuery before the API responds', async () => {
            logic = sqlEditorLogic({
                tabId: TAB_ID,
                monaco: createMockMonaco(),
                editor: createMockEditor(),
            })
            logic.mount()

            router.actions.push(urls.sqlEditor(), { open_insight: MOCK_INSIGHT_SHORT_ID })

            // Wait for the API response and the resulting actions, but verify
            // syncUrlWithQuery was NOT dispatched during the API wait
            await expectLogic(logic)
                .toDispatchActions(['editInsight', 'createTab', 'updateTab'])
                .toNotHaveDispatchedActions(['syncUrlWithQuery'])
        })
    })

    describe('open_query URL parameter', () => {
        const STACKED_BAR_NODE: DataVisualizationNode = {
            kind: NodeKind.DataVisualizationNode,
            source: {
                kind: NodeKind.HogQLQuery,
                query: 'SELECT toStartOfDay(timestamp) AS day, event, count() FROM events GROUP BY day, event',
            },
            display: ChartDisplayType.ActionsStackedBar,
            chartSettings: { seriesBreakdownColumn: 'event' },
        }

        it('adopts visualization settings and auto-runs when opening a serialized DataVisualizationNode', async () => {
            logic = sqlEditorLogic({
                tabId: TAB_ID,
                monaco: createMockMonaco(),
                editor: createMockEditor(),
            })
            logic.mount()

            // The URL Max's "Open as new insight" produces: insightNew redirects
            // HogQL-backed nodes to the SQL editor with the node in open_query
            router.actions.push(urls.insightNew({ query: STACKED_BAR_NODE }))

            await expectLogic(logic)
                .toDispatchActions(['createTab', 'setSourceQuery', 'runQuery'])
                .toMatchValues({
                    queryInput: STACKED_BAR_NODE.source.query,
                    sourceQuery: partial({
                        display: ChartDisplayType.ActionsStackedBar,
                        chartSettings: partial({ seriesBreakdownColumn: 'event' }),
                    }),
                })
        })

        it('keeps the default visualization and does not auto-run for a plain SQL string', async () => {
            logic = sqlEditorLogic({
                tabId: TAB_ID,
                monaco: createMockMonaco(),
                editor: createMockEditor(),
            })
            logic.mount()

            router.actions.push(urls.sqlEditor({ query: 'SELECT 1' }))

            await expectLogic(logic)
                .toDispatchActions(['createTab', 'setQueryInput'])
                .toNotHaveDispatchedActions(['runQuery'])
                .toMatchValues({
                    queryInput: 'SELECT 1',
                    sourceQuery: partial({ display: ChartDisplayType.Auto }),
                })
        })
    })

    describe('inline insight metadata editing', () => {
        async function loadInsight(): Promise<void> {
            logic = sqlEditorLogic({
                tabId: TAB_ID,
                monaco: createMockMonaco(),
                editor: createMockEditor(),
            })
            logic.mount()
            editorRootLogic = editorSceneLogic({ tabId: TAB_ID })
            editorRootLogic.mount()

            router.actions.push(urls.sqlEditor(), { open_insight: MOCK_INSIGHT_SHORT_ID })
            await expectLogic(logic)
                .toDispatchActions(['editInsight', 'createTab', 'updateTab'])
                .toMatchValues({ editingInsight: partial({ short_id: MOCK_INSIGHT_SHORT_ID }) })

            // Mirror what BindLogic does in production so updateInsightButtonEnabled has the saved query
            const visualizationLogic = dataVisualizationLogic({
                key: logic.values.dataLogicKey,
                query: MOCK_INSIGHT_QUERY,
                dataNodeCollectionId: logic.values.dataLogicKey,
            })
            visualizationLogic.mount()
        }

        it('seeds the active tab with the insight name and description on load', async () => {
            await loadInsight()

            expect(logic.values.activeTab?.name).toEqual(MOCK_INSIGHT.name)
            expect(logic.values.activeTab?.description).toEqual(MOCK_INSIGHT.description)
            expect(editorRootLogic!.values.updateInsightButtonEnabled).toEqual(false)
        })

        it('preserves an empty insight name instead of falling back to NEW_QUERY', async () => {
            logic = sqlEditorLogic({
                tabId: TAB_ID,
                monaco: createMockMonaco(),
                editor: createMockEditor(),
            })
            logic.mount()
            editorRootLogic = editorSceneLogic({ tabId: TAB_ID })
            editorRootLogic.mount()

            const insightWithEmptyName = { ...MOCK_INSIGHT, name: '' } as QueryBasedInsightModel
            logic.actions.createTab(MOCK_INSIGHT_QUERY.source.query, undefined, insightWithEmptyName)
            await expectLogic(logic).toDispatchActions(['createTab', 'updateTab'])

            expect(logic.values.activeTab?.name).toEqual('')
        })

        it.each([
            ['name', 'setEditingInsightName' as const, 'Renamed Insight'],
            ['description', 'setEditingInsightDescription' as const, 'A new description'],
        ])(
            'treats an inline %s edit as a pending change that enables Update insight',
            async (field, action, newValue) => {
                await loadInsight()

                logic.actions[action](newValue)

                expect(logic.values.activeTab?.[field as 'name' | 'description']).toEqual(newValue)
                expect(editorRootLogic!.values.updateInsightButtonEnabled).toEqual(true)
                expect(editorRootLogic!.values.titleSectionProps).toMatchObject({
                    [field]: newValue,
                })
            }
        )

        it('discards pending name and description edits when the insight is closed', async () => {
            await loadInsight()

            logic.actions.setEditingInsightName('Renamed Insight')
            logic.actions.setEditingInsightDescription('A new description')
            logic.actions.closeEditingObject()

            await expectLogic(logic).toDispatchActions(['closeEditingObject', 'updateTab']).toMatchValues({
                editingInsight: null,
            })

            expect(logic.values.activeTab?.name).toEqual('Untitled')
            expect(logic.values.activeTab?.description).toEqual('')
        })
    })

    describe('activeTabMatchesUrlTarget', () => {
        it.each([
            [
                'insight tab vs matching insight target',
                { name: 'Insight', insight: MOCK_INSIGHT },
                { insightShortId: MOCK_INSIGHT_SHORT_ID },
                true,
            ],
            ['view tab vs matching view target', { name: 'View', view: MOCK_VIEW }, { viewId: MOCK_VIEW.id }, true],
            [
                'draft tab vs matching draft target',
                { name: 'Draft', draft: MOCK_DRAFT },
                { draftId: MOCK_DRAFT.id },
                true,
            ],
            ['plain tab vs empty target', { name: 'Untitled' }, {}, true],
            ['plain tab vs insight target', { name: 'Untitled' }, { insightShortId: MOCK_INSIGHT_SHORT_ID }, false],
            ['plain tab vs view target', { name: 'Untitled' }, { viewId: MOCK_VIEW.id }, false],
            ['plain tab vs draft target', { name: 'Untitled' }, { draftId: MOCK_DRAFT.id }, false],
        ])('%s', (_, tab, target, expected) => {
            expect(
                activeTabMatchesUrlTarget(
                    {
                        uri: createMockMonaco().Uri.parse('tab-1'),
                        ...tab,
                    },
                    target
                )
            ).toEqual(expected)
        })
    })

    describe('open_view behavior', () => {
        it('respects the requested output tab when opening a view from the URL', async () => {
            logic = sqlEditorLogic({
                tabId: TAB_ID,
                monaco: createMockMonaco(),
                editor: createMockEditor(),
            })
            logic.mount()

            router.actions.push(urls.sqlEditor(), { open_view: MOCK_VIEW.id }, { output_tab: OutputTab.Results })

            await expectLogic(logic)
                .toDispatchActions(['setViewLoading', 'createTab', 'updateTab'])
                .toMatchValues({
                    editingView: partial({
                        id: MOCK_VIEW.id,
                    }),
                    outputActiveTab: OutputTab.Results,
                })
        })

        it('switches the active tab into the created view immediately after create success', async () => {
            logic = sqlEditorLogic({
                tabId: TAB_ID,
                monaco: createMockMonaco(),
                editor: createMockEditor(),
            })
            logic.mount()
            editorRootLogic = editorSceneLogic({ tabId: TAB_ID })
            editorRootLogic.mount()

            logic.actions.createTab('SELECT 1')
            await expectLogic(logic).toDispatchActions(['createTab', 'updateTab'])

            logic.actions.createDataWarehouseSavedQuerySuccess(
                [
                    {
                        id: 'created-view-id',
                        name: 'Created view',
                        query: {
                            kind: NodeKind.HogQLQuery,
                            query: 'SELECT 1',
                        },
                        is_materialized: false,
                        latest_history_id: null,
                        sync_frequency: null,
                        status: null,
                        last_run_at: null,
                        latest_error: null,
                    } as any,
                ],
                {
                    name: 'Created view',
                    query: {
                        kind: NodeKind.HogQLQuery,
                        query: 'SELECT 1',
                    },
                    types: [],
                }
            )

            await expectLogic(logic)
                .toDispatchActions(['createDataWarehouseSavedQuerySuccess', 'updateTab'])
                .toMatchValues({
                    editingView: partial({
                        id: 'created-view-id',
                        name: 'Created view',
                    }),
                })

            expect(editorRootLogic.values.titleSectionProps).toMatchObject({
                name: 'Created view',
            })
            await new Promise((resolve) => setTimeout(resolve, 0))

            expect(router.values.hashParams.view).toEqual('created-view-id')
        })

        it('keeps the results tab when opening a view directly', async () => {
            logic = sqlEditorLogic({
                tabId: TAB_ID,
                monaco: createMockMonaco(),
                editor: createMockEditor(),
            })
            logic.mount()

            logic.actions.editView(MOCK_VIEW.query.query, MOCK_VIEW)

            await expectLogic(logic)
                .toDispatchActions(['createTab', 'updateTab'])
                .toMatchValues({
                    editingView: partial({
                        id: MOCK_VIEW.id,
                    }),
                    outputActiveTab: OutputTab.Results,
                })
        })
    })

    describe('output tab hash parameter', () => {
        it('restores the selected output tab from the hash', async () => {
            logic = sqlEditorLogic({
                tabId: TAB_ID,
                monaco: createMockMonaco(),
                editor: createMockEditor(),
            })
            logic.mount()

            router.actions.push(urls.sqlEditor(), undefined, {
                q: 'SELECT 1',
                output_tab: OutputTab.Visualization,
            })

            await expectLogic(logic).toDispatchActions(['setActiveTab', 'createTab', 'updateTab']).toMatchValues({
                outputActiveTab: OutputTab.Visualization,
            })

            logic.actions.setQueryInput('SELECT 2')
            await new Promise((resolve) => setTimeout(resolve, 600))

            expect(router.values.hashParams.q).toEqual('SELECT 2')
            expect(router.values.hashParams.output_tab).toEqual(OutputTab.Visualization)
        })

        it('replaces the hash output tab when the selected tab changes', async () => {
            logic = sqlEditorLogic({
                tabId: TAB_ID,
                monaco: createMockMonaco(),
                editor: createMockEditor(),
            })
            logic.mount()

            logic.actions.createTab('SELECT 1')
            await expectLogic(logic).toDispatchActions(['createTab', 'updateTab'])

            logic.actions.setActiveTab(OutputTab.Visualization)
            await new Promise((resolve) => setTimeout(resolve, 0))

            expect(router.values.hashParams.q).toEqual('SELECT 1')
            expect(router.values.hashParams.output_tab).toEqual(OutputTab.Visualization)
        })

        it('uses both as the hash output tab when split view is selected', async () => {
            logic = sqlEditorLogic({
                tabId: TAB_ID,
                monaco: createMockMonaco(),
                editor: createMockEditor(),
            })
            logic.mount()

            logic.actions.createTab('SELECT 1')
            await expectLogic(logic).toDispatchActions(['createTab', 'updateTab'])

            logic.actions.setActiveTab(OutputTab.Both)
            await new Promise((resolve) => setTimeout(resolve, 0))

            expect(router.values.hashParams.q).toEqual('SELECT 1')
            expect(router.values.hashParams.output_tab).toEqual(OutputTab.Both)
        })

        it('coerces a numeric query hash param to a string instead of crashing splitQueryRanges', async () => {
            logic = sqlEditorLogic({
                tabId: TAB_ID,
                monaco: createMockMonaco(),
                editor: createMockEditor(),
            })
            logic.mount()

            // kea-router decodes `q=42` back to the number 42, which used to reach queryInput unchanged
            router.actions.push(urls.sqlEditor(), undefined, { q: 42 })

            await expectLogic(logic).toDispatchActions(['createTab', 'updateTab'])

            expect(logic.values.queryInput).toEqual('42')
            // Reading splitQueryRanges threw "e.trim is not a function" when queryInput was the number 42
            expect(() => logic.values.splitQueryRanges).not.toThrow()
            expect(logic.values.splitQueryRanges).toHaveLength(1)
        })
    })

    describe('source URL parameter', () => {
        it('remembers endpoint source when URL sync removes search params', async () => {
            logic = sqlEditorLogic({
                tabId: TAB_ID,
                monaco: createMockMonaco(),
                editor: createMockEditor(),
            })
            logic.mount()

            router.actions.push(urls.sqlEditor(), { source: 'endpoint' }, { q: 'SELECT 1' })

            await expectLogic(logic).toDispatchActions(['setEditorSource', 'createTab', 'updateTab'])

            logic.actions.setQueryInput('SELECT 2')
            await new Promise((resolve) => setTimeout(resolve, 600))

            expect(router.values.searchParams.source).toBeUndefined()
            expect(router.values.hashParams.q).toEqual('SELECT 2')
            expect(logic.values.editorSource).toEqual('endpoint')
        })

        it('shows back button to endpoints when endpoint source is active', async () => {
            logic = sqlEditorLogic({
                tabId: TAB_ID,
                monaco: createMockMonaco(),
                editor: createMockEditor(),
            })
            logic.mount()
            editorRootLogic = editorSceneLogic({ tabId: TAB_ID })
            editorRootLogic.mount()

            router.actions.push(urls.sqlEditor(), { source: 'endpoint' })

            await expectLogic(logic).toDispatchActions(['setEditorSource', 'createTab', 'updateTab'])

            expect(editorRootLogic.values.titleSectionProps.forceBackTo).toEqual({
                key: 'endpoints',
                name: 'Endpoints',
                path: urls.endpoints(),
                iconType: 'endpoints',
            })
        })

        it('remembers view source when URL sync removes search params', async () => {
            logic = sqlEditorLogic({
                tabId: TAB_ID,
                monaco: createMockMonaco(),
                editor: createMockEditor(),
            })
            logic.mount()

            router.actions.push(urls.sqlEditor(), { source: 'view' }, { q: 'SELECT 1' })

            await expectLogic(logic).toDispatchActions(['setEditorSource', 'createTab', 'updateTab'])

            logic.actions.setQueryInput('SELECT 2')
            await new Promise((resolve) => setTimeout(resolve, 600))

            expect(router.values.searchParams.source).toBeUndefined()
            expect(router.values.hashParams.q).toEqual('SELECT 2')
            expect(logic.values.editorSource).toEqual('view')
        })

        it('shows back button to models when view source is active', async () => {
            logic = sqlEditorLogic({
                tabId: TAB_ID,
                monaco: createMockMonaco(),
                editor: createMockEditor(),
            })
            logic.mount()
            editorRootLogic = editorSceneLogic({ tabId: TAB_ID })
            editorRootLogic.mount()

            router.actions.push(urls.sqlEditor(), { source: 'view' })

            await expectLogic(logic).toDispatchActions(['setEditorSource', 'createTab', 'updateTab'])

            expect(editorRootLogic.values.titleSectionProps.forceBackTo).toEqual({
                key: 'models',
                name: 'Models',
                path: urls.models(),
                iconType: 'sql_editor',
            })
        })

        it('ignores the legacy top-level connectionId when selecting the active connection', () => {
            logic = sqlEditorLogic({
                tabId: TAB_ID,
                monaco: createMockMonaco(),
                editor: createMockEditor(),
            })
            logic.mount()

            logic.actions.setSourceQuery({
                kind: NodeKind.DataVisualizationNode,
                connectionId: 'conn-123',
                source: {
                    kind: NodeKind.HogQLQuery,
                    query: 'SELECT 1',
                    connectionId: undefined,
                },
            } as DataVisualizationNode & { connectionId?: string })

            expect(logic.values.selectedConnectionId).toBeUndefined()
        })

        it('reads connection id from hash and keeps it in URL sync', async () => {
            logic = sqlEditorLogic({
                tabId: TAB_ID,
                monaco: createMockMonaco(),
                editor: createMockEditor(),
            })
            logic.mount()

            router.actions.push(urls.sqlEditor(), undefined, { q: 'SELECT 1', c: 'conn-123' })

            await expectLogic(logic).toDispatchActions(['setSourceQuery', 'createTab', 'updateTab'])

            expect(logic.values.sourceQuery.source.connectionId).toEqual('conn-123')
            expect(router.values.hashParams.c).toEqual('conn-123')

            logic.actions.setQueryInput('SELECT 2')
            await new Promise((resolve) => setTimeout(resolve, 600))

            expect(router.values.hashParams.q).toEqual('SELECT 2')
            expect(router.values.hashParams.c).toEqual('conn-123')
        })

        it('reads send raw query from hash and keeps it in URL sync', async () => {
            logic = sqlEditorLogic({
                tabId: TAB_ID,
                monaco: createMockMonaco(),
                editor: createMockEditor(),
            })
            logic.mount()

            router.actions.push(urls.sqlEditor(), undefined, { q: 'SELECT 1', c: 'conn-123', raw: '1' })

            await expectLogic(logic).toDispatchActions(['setSourceQuery', 'createTab', 'updateTab'])

            expect(logic.values.sourceQuery.source.connectionId).toEqual('conn-123')
            expect(logic.values.sendRawQueryEnabled).toEqual(true)
            expect(String(router.values.hashParams.raw)).toEqual('1')

            logic.actions.setQueryInput('SELECT 2')
            await new Promise((resolve) => setTimeout(resolve, 600))

            expect(router.values.hashParams.q).toEqual('SELECT 2')
            expect(router.values.hashParams.c).toEqual('conn-123')
            expect(String(router.values.hashParams.raw)).toEqual('1')
        })

        it('ignores send raw query from hash for PostHog warehouse', async () => {
            logic = sqlEditorLogic({
                tabId: TAB_ID,
                monaco: createMockMonaco(),
                editor: createMockEditor(),
            })
            logic.mount()

            router.actions.push(urls.sqlEditor(), undefined, { q: 'SELECT 1', raw: '1' })

            await expectLogic(logic).toDispatchActions(['createTab', 'updateTab'])

            expect(logic.values.sourceQuery.source.connectionId).toBeUndefined()
            expect(logic.values.sendRawQueryEnabled).toEqual(false)
            expect(logic.values.sourceQuery.source.sendRawQuery).toBeUndefined()
        })

        it('keeps send raw query enabled after the first toggle', async () => {
            logic = sqlEditorLogic({
                tabId: TAB_ID,
                monaco: createMockMonaco(),
                editor: createMockEditor(),
            })
            logic.mount()

            router.actions.push(urls.sqlEditor(), undefined, { q: 'SELECT 1', c: 'conn-123' })

            await expectLogic(logic).toDispatchActions(['setSourceQuery', 'createTab', 'updateTab'])

            logic.actions.setSendRawQuery(true)
            await new Promise((resolve) => setTimeout(resolve, 0))

            expect(logic.values.sendRawQueryEnabled).toEqual(true)
            expect(logic.values.sourceQuery.source.connectionId).toEqual('conn-123')
            expect(String(router.values.hashParams.raw)).toEqual('1')
        })

        it('strips legacy top-level connection ids when source query changes', async () => {
            logic = sqlEditorLogic({
                tabId: TAB_ID,
                monaco: createMockMonaco(),
                editor: createMockEditor(),
            })
            logic.mount()

            router.actions.push(urls.sqlEditor(), undefined, { q: 'SELECT 1' })

            await expectLogic(logic).toDispatchActions(['createTab', 'updateTab'])

            const sourceQueryWithLegacyConnectionId = {
                ...logic.values.sourceQuery,
                connectionId: 'legacy-conn-123',
                source: {
                    ...logic.values.sourceQuery.source,
                    connectionId: 'conn-123',
                    sendRawQuery: true,
                },
            } as DataVisualizationNode & { connectionId?: string }

            logic.actions.setSourceQuery(sourceQueryWithLegacyConnectionId as DataVisualizationNode)
            await new Promise((resolve) => setTimeout(resolve, 0))

            expect('connectionId' in logic.values.sourceQuery).toEqual(false)
            expect(logic.values.sourceQuery.source.connectionId).toEqual('conn-123')
            expect(logic.values.sourceQuery.source.sendRawQuery).toEqual(true)
            expect(logic.values.activeTab?.sourceQuery).not.toBeUndefined()
            expect(
                logic.values.activeTab?.sourceQuery ? 'connectionId' in logic.values.activeTab.sourceQuery : false
            ).toEqual(false)
        })

        it("doesn't enable send raw query for PostHog warehouse", async () => {
            logic = sqlEditorLogic({
                tabId: TAB_ID,
                monaco: createMockMonaco(),
                editor: createMockEditor(),
            })
            logic.mount()

            router.actions.push(urls.sqlEditor(), undefined, { q: 'SELECT 1' })

            await expectLogic(logic).toDispatchActions(['createTab', 'updateTab'])

            logic.actions.setSendRawQuery(true)
            await new Promise((resolve) => setTimeout(resolve, 0))

            expect(logic.values.sendRawQueryEnabled).toEqual(false)
            expect(logic.values.sourceQuery.source.sendRawQuery).toBeUndefined()
            expect(router.values.hashParams.raw).toBeUndefined()
        })

        it('loads the scoped schema only once when a connection id is present in the hash', async () => {
            const performQuerySpy = jest
                .spyOn(queryRunner, 'performQuery')
                .mockResolvedValue({ tables: {}, joins: [] } as never)

            logic = sqlEditorLogic({
                tabId: TAB_ID,
                monaco: createMockMonaco(),
                editor: createMockEditor(),
            })
            logic.mount()

            router.actions.push(urls.sqlEditor(), undefined, { q: 'SELECT 1', c: 'conn-123' })

            await expectLogic(logic).toDispatchActions(['setSourceQuery', 'createTab', 'updateTab'])
            await new Promise((resolve) => setTimeout(resolve, 0))

            expect(performQuerySpy).toHaveBeenCalledTimes(1)
            expect(performQuerySpy.mock.calls[0][0]).toMatchObject({ connectionId: 'conn-123' })
            expect(databaseLogic.values.connectionId).toEqual('conn-123')

            performQuerySpy.mockRestore()
        })

        it('resets stale database connection state when reopening the editor without a connection in the url', async () => {
            const performQuerySpy = jest
                .spyOn(queryRunner, 'performQuery')
                .mockResolvedValue({ tables: {}, joins: [] } as never)

            databaseLogic.actions.setConnection('conn-123')
            await databaseLogic.asyncActions.loadDatabase()
            performQuerySpy.mockClear()
            window.history.replaceState({}, '', urls.sqlEditor())

            logic = sqlEditorLogic({
                tabId: TAB_ID,
                monaco: createMockMonaco(),
                editor: createMockEditor(),
            })
            logic.mount()

            await new Promise((resolve) => setTimeout(resolve, 0))

            expect(logic.values.selectedConnectionId).toBeUndefined()
            expect(databaseLogic.values.connectionId).toBeNull()
            expect(performQuerySpy).toHaveBeenCalledTimes(1)
            expect(performQuerySpy.mock.calls[0][0]).toMatchObject({ connectionId: undefined })

            performQuerySpy.mockRestore()
        })

        it('passes sendRawQuery when running a direct query', async () => {
            const performQuerySpy = jest
                .spyOn(queryRunner, 'performQuery')
                .mockResolvedValue({ results: [], columns: [], types: [] } as never)

            logic = sqlEditorLogic({
                tabId: TAB_ID,
                monaco: createMockMonaco(),
                editor: createMockEditor(),
            })
            logic.mount()

            router.actions.push(urls.sqlEditor(), undefined, { q: 'SELECT 1', c: 'conn-123' })

            await expectLogic(logic).toDispatchActions(['setSourceQuery', 'createTab', 'updateTab'])
            await new Promise((resolve) => setTimeout(resolve, 0))

            performQuerySpy.mockClear()

            logic.actions.setSourceQuery({
                ...logic.values.sourceQuery,
                source: {
                    ...logic.values.sourceQuery.source,
                    sendRawQuery: true,
                },
            })

            expect(logic.values.sourceQuery.source.sendRawQuery).toEqual(true)

            logic.actions.runQuery()
            await new Promise((resolve) => setTimeout(resolve, 0))

            expect(performQuerySpy).toHaveBeenCalled()
            expect(performQuerySpy.mock.calls[0][0]).toMatchObject({
                kind: NodeKind.HogQLQuery,
                query: 'SELECT 1',
                connectionId: 'conn-123',
                sendRawQuery: true,
            })

            performQuerySpy.mockRestore()
        })

        it("doesn't pass sendRawQuery when running against PostHog warehouse", async () => {
            const performQuerySpy = jest
                .spyOn(queryRunner, 'performQuery')
                .mockResolvedValue({ results: [], columns: [], types: [] } as never)

            logic = sqlEditorLogic({
                tabId: TAB_ID,
                monaco: createMockMonaco(),
                editor: createMockEditor(),
            })
            logic.mount()

            router.actions.push(urls.sqlEditor(), undefined, { q: 'SELECT 1' })

            await expectLogic(logic).toDispatchActions(['createTab', 'updateTab'])
            await new Promise((resolve) => setTimeout(resolve, 0))

            performQuerySpy.mockClear()

            logic.actions.setSourceQuery({
                ...logic.values.sourceQuery,
                source: {
                    ...logic.values.sourceQuery.source,
                    sendRawQuery: true,
                },
            })

            logic.actions.runQuery()
            await new Promise((resolve) => setTimeout(resolve, 0))

            expect(performQuerySpy).toHaveBeenCalled()
            expect(performQuerySpy.mock.calls[0][0]).toMatchObject({
                kind: NodeKind.HogQLQuery,
                query: 'SELECT 1',
                sendRawQuery: undefined,
            })
            expect(performQuerySpy.mock.calls[0][0]).not.toHaveProperty('connectionId')
            expect(logic.values.sendRawQueryEnabled).toEqual(false)
            expect(logic.values.sourceQuery.source.sendRawQuery).toBeUndefined()

            performQuerySpy.mockRestore()
        })
    })

    describe('AI suggestion undo', () => {
        const ORIGINAL = 'SELECT 1'
        const ACCEPTED = 'SELECT 2 FROM events'

        // A Monaco model that records pushEditOperations as if it had a real undo stack,
        // so we can assert the accepted query is applied as an undoable edit rather than a
        // model.setValue (which would wipe history).
        function createUndoTrackingModel(initialValue: string): any {
            let value = initialValue
            return {
                getValue: () => value,
                getFullModelRange: () => ({
                    startLineNumber: 1,
                    startColumn: 1,
                    endLineNumber: 1,
                    endColumn: value.length + 1,
                }),
                pushStackElement: jest.fn(),
                pushEditOperations: jest.fn((_before: any, ops: any[]) => {
                    value = ops[0].text
                    return null
                }),
                setValue: jest.fn((next: string) => {
                    value = next
                }),
                onDidChangeContent: jest.fn(() => ({ dispose: jest.fn() })),
                dispose: jest.fn(),
            }
        }

        function createMonacoWithModel(model: any): any {
            const monaco = createMockMonaco()
            monaco.editor.getModel = () => model
            monaco.editor.createModel = () => model
            return monaco
        }

        function mountWithModel(model: any): any {
            const monaco = createMonacoWithModel(model)
            logic = sqlEditorLogic({ tabId: TAB_ID, monaco, editor: createMockEditor() })
            logic.mount()
            // Establish an active tab so accept/reject can resolve the model URI.
            logic.actions.updateTab({ uri: monaco.Uri.parse(`tab-${TAB_ID}`), name: 'SQL' } as any)
            return monaco
        }

        it('applies an accepted suggestion to the persistent model as an undoable edit', () => {
            const model = createUndoTrackingModel(ORIGINAL)
            mountWithModel(model)

            logic.actions.setQueryInput(ORIGINAL)
            logic.actions._setSuggestionPayload({
                suggestedValue: ACCEPTED,
                originalValue: ORIGINAL,
                source: 'max_ai',
                onAccept: (_shouldRun, actions) => actions.setQueryInput(ACCEPTED),
                onReject: () => {},
            })
            logic.actions.onAcceptSuggestedQueryInput()

            // Undoable edit, not setValue — preserves the existing undo history.
            expect(model.pushEditOperations).toHaveBeenCalledWith(
                [],
                [expect.objectContaining({ text: ACCEPTED })],
                expect.any(Function)
            )
            expect(model.setValue).not.toHaveBeenCalled()
            expect(model.getValue()).toEqual(ACCEPTED)
        })

        // Both cases leave the model already holding the target query, so no undoable edit
        // should be pushed (the no-op guard in applyUndoableModelEdit).
        it.each([
            {
                name: 'the accepted query already matches the model',
                payload: {
                    suggestedValue: ORIGINAL,
                    onAccept: (_shouldRun: boolean, actions: any) => actions.setQueryInput(ORIGINAL),
                    onReject: () => {},
                },
                act: () => logic.actions.onAcceptSuggestedQueryInput(),
            },
            {
                name: 'a suggestion is rejected',
                payload: {
                    suggestedValue: ACCEPTED,
                    onAccept: () => {},
                    onReject: (actions: any) => actions.setQueryInput(ORIGINAL),
                },
                act: () => logic.actions.onRejectSuggestedQueryInput(),
            },
        ])('does not push an undoable edit when $name', ({ payload, act }) => {
            const model = createUndoTrackingModel(ORIGINAL)
            mountWithModel(model)

            logic.actions.setQueryInput(ORIGINAL)
            logic.actions._setSuggestionPayload({ originalValue: ORIGINAL, source: 'max_ai', ...payload })
            act()

            expect(model.pushEditOperations).not.toHaveBeenCalled()
        })
    })

    describe('attaching the dashboard when saving from a dashboard flow', () => {
        const DASHBOARD_ID = 99

        afterEach(() => {
            jest.restoreAllMocks()
        })

        it.each([
            { name: 'passes dashboards to insightsApi.create when a dashboardId is set', dashboardId: DASHBOARD_ID },
            { name: 'does not pass dashboards to insightsApi.create when no dashboardId is set', dashboardId: null },
        ])('$name', async ({ dashboardId }) => {
            const createSpy = jest.spyOn(insightsApi, 'create').mockResolvedValue(MOCK_INSIGHT)

            logic = sqlEditorLogic({
                tabId: TAB_ID,
                monaco: createMockMonaco(),
                editor: createMockEditor(),
            })
            logic.mount()

            logic.actions.createTab('SELECT count() FROM events')
            await expectLogic(logic).toDispatchActions(['createTab', 'updateTab'])
            if (dashboardId !== null) {
                logic.actions.setDashboardId(dashboardId)
            }

            logic.actions.saveAsInsightSubmit('My SQL insight')
            await expectLogic(logic).toFinishAllListeners()

            expect(createSpy).toHaveBeenCalledTimes(1)
            const createPayload = createSpy.mock.calls[0][0]
            expect(createPayload).toMatchObject({ name: 'My SQL insight', saved: true })
            if (dashboardId !== null) {
                expect(createPayload.dashboards).toEqual([dashboardId])
            } else {
                expect(createPayload).not.toHaveProperty('dashboards')
            }
        })

        // The update path unions the target dashboard with the insight's existing links, read
        // from both dashboard_tiles (preferred) and the legacy dashboards field, deduped.
        it.each([
            {
                name: 'merges the dashboard with existing legacy dashboards links',
                dashboards: [7],
                dashboardTiles: [],
                expected: [7, DASHBOARD_ID],
            },
            {
                name: 'merges the dashboard with existing dashboard_tiles links',
                dashboards: [],
                dashboardTiles: [{ id: 1, dashboard_id: 7, deleted: null }],
                expected: [7, DASHBOARD_ID],
            },
            {
                name: 'does not duplicate a dashboard the insight is already linked to',
                dashboards: [],
                dashboardTiles: [{ id: 1, dashboard_id: DASHBOARD_ID, deleted: null }],
                expected: [DASHBOARD_ID],
            },
        ])('$name', async ({ dashboards, dashboardTiles, expected }) => {
            const updateSpy = jest.spyOn(insightsApi, 'update').mockResolvedValue(MOCK_INSIGHT)

            logic = sqlEditorLogic({
                tabId: TAB_ID,
                monaco: createMockMonaco(),
                editor: createMockEditor(),
            })
            logic.mount()
            editorRootLogic = editorSceneLogic({ tabId: TAB_ID })
            editorRootLogic.mount()

            const insightOnDashboards = {
                ...MOCK_INSIGHT,
                dashboards,
                dashboard_tiles: dashboardTiles,
            } as QueryBasedInsightModel
            logic.actions.editInsight(MOCK_INSIGHT_QUERY.source.query, insightOnDashboards)
            await expectLogic(logic)
                .toDispatchActions(['createTab', 'updateTab'])
                .toMatchValues({ editingInsight: partial({ short_id: MOCK_INSIGHT_SHORT_ID }) })

            logic.actions.setDashboardId(DASHBOARD_ID)
            logic.actions.updateInsight()
            await expectLogic(logic).toFinishAllListeners()

            expect(updateSpy).toHaveBeenCalledTimes(1)
            const [, updatePayload] = updateSpy.mock.calls[0]
            // Order-independent: only the set of linked dashboards matters.
            expect([...(updatePayload.dashboards ?? [])].sort()).toEqual([...expected].sort())
        })
    })

    describe('materialize on save', () => {
        it.each([
            { name: 'materializes the created view when materializeAfterSave is true', materialize: true },
            { name: 'does not materialize when materializeAfterSave is false', materialize: false },
        ])('$name', async ({ materialize }) => {
            const viewsLogic = dataWarehouseViewsLogic()
            viewsLogic.mount()

            logic = sqlEditorLogic({
                tabId: TAB_ID,
                monaco: createMockMonaco(),
                editor: createMockEditor(),
            })
            logic.mount()

            logic.actions.createTab('SELECT 1')
            await expectLogic(logic).toDispatchActions(['createTab', 'updateTab'])
            logic.actions.setQueryInput('SELECT 1')

            // saveAsViewSubmit reads the editor's dataNodeLogic for inferred column types; in the
            // app it's mounted by the visualization, so mount a matching one here.
            const editorDataNodeLogic = dataNodeLogic({
                key: logic.values.dataLogicKey,
                query: { kind: NodeKind.HogQLQuery, query: 'SELECT 1' },
            })
            editorDataNodeLogic.mount()

            logic.actions.saveAsViewSubmit('Materialized view', materialize)

            await expectLogic(viewsLogic).toDispatchActions(['createDataWarehouseSavedQuerySuccess'])
            await expectLogic(viewsLogic).toFinishAllListeners()

            if (materialize) {
                expect(materializeEndpointMock).toHaveBeenCalledTimes(1)
                // Guard against passing the wrong (or undefined) view id to the materialize call.
                expect(materializeEndpointMock).toHaveBeenCalledWith(
                    expect.objectContaining({ params: expect.objectContaining({ id: 'created-view-id' }) })
                )
            } else {
                expect(materializeEndpointMock).toHaveBeenCalledTimes(0)
            }

            editorDataNodeLogic.unmount()
            viewsLogic.unmount()
        })
    })
})
