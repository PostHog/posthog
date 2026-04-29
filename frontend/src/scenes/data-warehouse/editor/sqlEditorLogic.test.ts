import { router } from 'kea-router'
import { expectLogic, partial } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
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
    let databaseLogic: ReturnType<typeof databaseTableListLogic.build>
    const TAB_ID = '1'
    let queryEndpointMock: jest.Mock

    beforeEach(async () => {
        queryEndpointMock = jest.fn(() => [200, { tables: {}, joins: [] }])
        useMocks({
            get: {
                '/api/environments/:team_id/insights/': (req) => {
                    const shortId = req.url.searchParams.get('short_id')
                    if (shortId === MOCK_INSIGHT_SHORT_ID) {
                        return [200, { results: [MOCK_INSIGHT] }]
                    }
                    if (shortId === MOCK_DATA_TABLE_INSIGHT_SHORT_ID) {
                        return [200, { results: [MOCK_DATA_TABLE_INSIGHT] }]
                    }
                    return [200, { results: [] }]
                },
                '/api/environments/:team_id/warehouse_saved_queries/': { results: [MOCK_VIEW] },
                '/api/environments/:team_id/warehouse_saved_queries/:id/': (req) => {
                    if (req.params.id === MOCK_VIEW.id) {
                        return [200, MOCK_VIEW]
                    }
                    return [404]
                },
                '/api/environments/:team_id/lineage/get_upstream/': { nodes: [], edges: [] },
                '/api/user_home_settings/@me/': {},
            },
            post: {
                '/api/environments/:team_id/query/': queryEndpointMock,
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
        sceneLogic.actions.setTabs([
            { id: TAB_ID, title: 'SQL', pathname: '/sql', search: '', hash: '', active: true, iconType: 'blank' },
        ])
        await expectLogic(teamLogic).toFinishAllListeners()
    })

    afterEach(() => {
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

            window.history.replaceState({}, '', `${urls.sqlEditor()}?open_view=test-view`)

            expect(logic.values.titleSectionProps.name).toEqual('Loading view...')
        })

        it('shows loading insight title when opening an insight from URL before insight loads', async () => {
            logic = sqlEditorLogic({
                tabId: TAB_ID,
                monaco: createMockMonaco(),
                editor: createMockEditor(),
            })
            logic.mount()

            window.history.replaceState({}, '', `${urls.sqlEditor()}?open_insight=${MOCK_INSIGHT_SHORT_ID}`)

            expect(logic.values.titleSectionProps.name).toEqual('Loading insight...')
        })

        it('closes an insight into an unsaved query without clearing SQL or visualization settings', async () => {
            logic = sqlEditorLogic({
                tabId: TAB_ID,
                monaco: createMockMonaco(),
                editor: createMockEditor(),
            })
            logic.mount()

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
                    titleSectionProps: partial({
                        name: 'New SQL query',
                    }),
                    sourceQuery: partial({
                        display: ChartDisplayType.BoldNumber,
                    }),
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
                    titleSectionProps: partial({
                        name: 'New SQL query',
                    }),
                    sourceQuery: partial({
                        display: ChartDisplayType.ActionsBar,
                    }),
                })

            expect(window.location.hash).not.toContain('view')
            expect(window.location.search).not.toContain('open_view')
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
            expect(logic.values.updateInsightButtonEnabled).toEqual(false)
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
                    titleSectionProps: partial({
                        name: 'Created view',
                    }),
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

            router.actions.push(urls.sqlEditor(), { source: 'endpoint' })

            await expectLogic(logic).toDispatchActions(['setEditorSource', 'createTab', 'updateTab'])

            expect(logic.values.titleSectionProps.forceBackTo).toEqual({
                key: 'endpoints',
                name: 'Endpoints',
                path: urls.endpoints(),
                iconType: 'endpoints',
            })
        })

        it('ignores the legacy top-level connectionId when selecting the active connection', () => {
            logic = sqlEditorLogic({
                tabId: TAB_ID,
                monaco: createMockMonaco(),
                editor: createMockEditor(),
            })
            logic.mount()
            featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.DWH_POSTGRES_DIRECT_QUERY], {
                [FEATURE_FLAGS.DWH_POSTGRES_DIRECT_QUERY]: true,
            })

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
            featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.DWH_POSTGRES_DIRECT_QUERY], {
                [FEATURE_FLAGS.DWH_POSTGRES_DIRECT_QUERY]: true,
            })

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
            featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.DWH_POSTGRES_DIRECT_QUERY], {
                [FEATURE_FLAGS.DWH_POSTGRES_DIRECT_QUERY]: true,
            })

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
            featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.DWH_POSTGRES_DIRECT_QUERY], {
                [FEATURE_FLAGS.DWH_POSTGRES_DIRECT_QUERY]: true,
            })

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
            featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.DWH_POSTGRES_DIRECT_QUERY], {
                [FEATURE_FLAGS.DWH_POSTGRES_DIRECT_QUERY]: true,
            })

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
            featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.DWH_POSTGRES_DIRECT_QUERY], {
                [FEATURE_FLAGS.DWH_POSTGRES_DIRECT_QUERY]: true,
            })

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
            featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.DWH_POSTGRES_DIRECT_QUERY], {
                [FEATURE_FLAGS.DWH_POSTGRES_DIRECT_QUERY]: true,
            })

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

            featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.DWH_POSTGRES_DIRECT_QUERY], {
                [FEATURE_FLAGS.DWH_POSTGRES_DIRECT_QUERY]: true,
            })

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
            featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.DWH_POSTGRES_DIRECT_QUERY], {
                [FEATURE_FLAGS.DWH_POSTGRES_DIRECT_QUERY]: true,
            })

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
            featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.DWH_POSTGRES_DIRECT_QUERY], {
                [FEATURE_FLAGS.DWH_POSTGRES_DIRECT_QUERY]: true,
            })

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
})
