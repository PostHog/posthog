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
import { DataVisualizationNode, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { ChartDisplayType, InsightShortId, QueryBasedInsightModel } from '~/types'

import { OutputTab } from './outputPaneLogic'
import { getDisplayTypeToSaveInsight, sqlEditorLogic } from './sqlEditorLogic'

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

    describe('open_view behavior', () => {
        it('switches to the materialization tab when opening a view from the URL', async () => {
            logic = sqlEditorLogic({
                tabId: TAB_ID,
                monaco: createMockMonaco(),
                editor: createMockEditor(),
            })
            logic.mount()

            router.actions.push(urls.sqlEditor(), { open_view: MOCK_VIEW.id, output_tab: OutputTab.Results })

            await expectLogic(logic)
                .toDispatchActions(['setActiveTab', 'setViewLoading', 'editView', 'createTab', 'updateTab'])
                .toMatchValues({
                    editingView: partial({
                        id: MOCK_VIEW.id,
                    }),
                    outputActiveTab: OutputTab.Materialization,
                })
        })

        it('switches to the materialization tab when opening a view directly', async () => {
            logic = sqlEditorLogic({
                tabId: TAB_ID,
                monaco: createMockMonaco(),
                editor: createMockEditor(),
            })
            logic.mount()

            logic.actions.editView(MOCK_VIEW.query.query, MOCK_VIEW)

            await expectLogic(logic)
                .toDispatchActions(['setActiveTab', 'createTab', 'updateTab'])
                .toMatchValues({
                    editingView: partial({
                        id: MOCK_VIEW.id,
                    }),
                    outputActiveTab: OutputTab.Materialization,
                })
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
    })
})
