import { router } from 'kea-router'
import { expectLogic, partial } from 'kea-test-utils'

import { sceneLogic } from 'scenes/sceneLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { DataVisualizationNode, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { InsightShortId, QueryBasedInsightModel } from '~/types'

import { sqlEditorLogic } from './sqlEditorLogic'

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
    const TAB_ID = '1'

    beforeEach(async () => {
        useMocks({
            get: {
                '/api/environments/:team_id/insights/': (req) => {
                    const shortId = req.url.searchParams.get('short_id')
                    if (shortId === MOCK_INSIGHT_SHORT_ID) {
                        return [200, { results: [MOCK_INSIGHT] }]
                    }
                    return [200, { results: [] }]
                },
                '/api/environments/:team_id/warehouse_saved_queries/': { results: [] },
                '/api/environments/:team_id/warehouse_saved_queries/:id/': [404],
                '/api/user_home_settings/@me/': {},
            },
            post: {
                '/api/environments/:team_id/query/': { results: [] },
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
        sceneLogic.actions.setTabs([
            { id: TAB_ID, title: 'SQL', pathname: '/sql', search: '', hash: '', active: true, iconType: 'blank' },
        ])
        await expectLogic(teamLogic).toFinishAllListeners()
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
    })
})
