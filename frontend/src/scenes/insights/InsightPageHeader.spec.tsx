import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { BindLogic } from 'kea'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { Node } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel, InsightShortId, QueryBasedInsightModel, ItemMode } from '~/types'

import { insightLogic } from './insightLogic'
import { InsightPageHeader } from './InsightPageHeader'
import { insightSceneLogic } from './insightSceneLogic'

jest.mock('./SidePanel/InsightSidePanelContent', () => ({
    InsightSidePanelContent: () => null,
}))
const mockUseMaxTool = jest.fn().mockReturnValue({ openMax: jest.fn(), definition: null })
jest.mock('scenes/max/useMaxTool', () => ({
    useMaxTool: (...args: unknown[]) => mockUseMaxTool(...args),
}))

const TAB_ID = 'test-tab'
const SAVED_INSIGHT_ID = 'abc123' as InsightShortId

const MOCK_INSIGHT_BASE: QueryBasedInsightModel = {
    id: 1,
    short_id: SAVED_INSIGHT_ID,
    name: 'Test Insight',
    description: '',
    dashboards: [],
    dashboard_tiles: [],
    query: { kind: 'TrendsQuery', series: [{ kind: 'EventsNode', event: '$pageview' }] } as Node,
    result: [],
    saved: true,
    tags: [],
    order: null,
    deleted: false,
    created_at: '2024-01-01T00:00:00.000Z',
    created_by: null,
    is_sample: false,
    updated_at: '2024-01-01T00:00:00.000Z',
    last_modified_at: '2024-01-01T00:00:00.000Z',
    last_modified_by: null,
    last_refresh: null,
    user_access_level: AccessControlLevel.Editor,
}

function makeInsight(overrides: Partial<QueryBasedInsightModel> = {}): QueryBasedInsightModel {
    return { ...MOCK_INSIGHT_BASE, ...overrides }
}

function queryByAttr(attr: string): HTMLElement | null {
    return document.querySelector(`[data-attr="${attr}"]`)
}

beforeAll(() => {
    const root = document.createElement('div')
    root.id = 'root'
    document.body.appendChild(root)
})

describe('InsightPageHeader', () => {
    let mountedLogics: { unmount: () => void }[] = []

    beforeEach(() => {
        localStorage.clear()
        sessionStorage.clear()
        useMocks({
            post: {
                '/api/environments/:team_id/query/': () => [200, { results: [] }],
            },
        })
        initKeaTests()
        featureFlagLogic.mount()
        mockUseMaxTool.mockClear()
    })

    afterEach(() => {
        for (const logic of mountedLogics) {
            logic.unmount()
        }
        mountedLogics = []
        cleanup()
    })

    function renderHeader(opts: {
        insightMode: ItemMode
        dashboardItemId: InsightShortId | 'new'
        insight?: QueryBasedInsightModel
    }): {
        sceneLogic: ReturnType<typeof insightSceneLogic.build>
        iLogic: ReturnType<typeof insightLogic.build>
    } {
        const { insightMode, dashboardItemId, insight } = opts
        const insightData = insight ?? makeInsight({ user_access_level: AccessControlLevel.Editor })

        const sceneLogic = insightSceneLogic({ tabId: TAB_ID })
        sceneLogic.mount()
        sceneLogic.actions.setSceneState(
            (dashboardItemId === 'new' ? 'new' : dashboardItemId) as InsightShortId,
            insightMode,
            undefined,
            undefined,
            undefined,
            undefined,
            undefined,
            undefined,
            undefined,
            null
        )

        const insightLogicProps = { dashboardItemId, doNotLoad: true }
        const iLogic = insightLogic(insightLogicProps)
        iLogic.mount()
        iLogic.actions.loadInsightSuccess(insightData)

        mountedLogics.push(iLogic, sceneLogic)

        render(
            <BindLogic logic={insightSceneLogic} props={{ tabId: TAB_ID }}>
                <InsightPageHeader insightLogicProps={insightLogicProps} />
            </BindLogic>
        )

        return { sceneLogic, iLogic }
    }

    describe('action buttons', () => {
        it.each([
            {
                scenario: 'New unsaved insight',
                insightMode: ItemMode.Edit,
                dashboardItemId: 'new' as const,
                canEdit: true,
                visible: ['insight-save-button'],
                notVisible: ['insight-cancel-edit-button', 'insight-edit-button'],
            },
            {
                scenario: 'Saved insight, View mode, can edit',
                insightMode: ItemMode.View,
                dashboardItemId: SAVED_INSIGHT_ID,
                canEdit: true,
                visible: ['insight-edit-button'],
                notVisible: ['insight-cancel-edit-button', 'insight-save-button'],
            },
            {
                scenario: 'Saved insight, View mode, cannot edit',
                insightMode: ItemMode.View,
                dashboardItemId: SAVED_INSIGHT_ID,
                canEdit: false,
                visible: [] as string[],
                notVisible: ['insight-edit-button', 'insight-cancel-edit-button', 'insight-save-button'],
            },
            {
                scenario: 'Saved insight, Edit mode, can edit',
                insightMode: ItemMode.Edit,
                dashboardItemId: SAVED_INSIGHT_ID,
                canEdit: true,
                visible: ['insight-cancel-edit-button', 'insight-save-button'],
                notVisible: ['insight-edit-button'],
            },
            {
                scenario: 'Saved insight, Edit mode, cannot edit',
                insightMode: ItemMode.Edit,
                dashboardItemId: SAVED_INSIGHT_ID,
                canEdit: false,
                visible: ['insight-cancel-edit-button', 'insight-save-button'],
                notVisible: ['insight-edit-button'],
            },
        ])(
            '$scenario: shows the correct action buttons',
            ({ insightMode, dashboardItemId, canEdit, visible, notVisible }) => {
                const insight = makeInsight({
                    user_access_level: canEdit ? AccessControlLevel.Editor : AccessControlLevel.Viewer,
                })
                renderHeader({ insightMode, dashboardItemId, insight })

                for (const attr of visible) {
                    expect(queryByAttr(attr)).toBeInTheDocument()
                }
                for (const attr of notVisible) {
                    expect(queryByAttr(attr)).not.toBeInTheDocument()
                }
            }
        )
    })

    describe('alert tool', () => {
        it('is inactive when the query type does not support alerts', () => {
            const insight = makeInsight({
                user_access_level: AccessControlLevel.Editor,
                query: { kind: 'DataTableNode', source: { kind: 'EventsQuery' } } as Node,
            })
            renderHeader({
                insightMode: ItemMode.View,
                dashboardItemId: SAVED_INSIGHT_ID,
                insight,
            })

            const alertCall = mockUseMaxTool.mock.calls.find(
                (call: Record<string, unknown>[]) => call[0]?.identifier === 'upsert_alert'
            )
            expect(alertCall).not.toBeUndefined()
            expect(alertCall![0].active).toBe(false)
        })

        it('is active when the query supports alerts and the insight is saved', () => {
            const insight = makeInsight({
                user_access_level: AccessControlLevel.Editor,
                query: {
                    kind: 'InsightVizNode',
                    source: {
                        kind: 'TrendsQuery',
                        trendsFilter: {},
                        series: [{ kind: 'EventsNode', event: '$pageview' }],
                    },
                } as Node,
            })
            renderHeader({
                insightMode: ItemMode.View,
                dashboardItemId: SAVED_INSIGHT_ID,
                insight,
            })

            const alertCall = mockUseMaxTool.mock.calls.find(
                (call: Record<string, unknown>[]) => call[0]?.identifier === 'upsert_alert'
            )
            expect(alertCall).not.toBeUndefined()
            expect(alertCall![0].active).toBe(true)
        })
    })

    describe('forceEdit', () => {
        it('shows the editable name input in Edit mode', () => {
            renderHeader({
                insightMode: ItemMode.Edit,
                dashboardItemId: SAVED_INSIGHT_ID,
                insight: makeInsight({ user_access_level: AccessControlLevel.Editor }),
            })

            expect(screen.getByPlaceholderText('Enter name')).toBeInTheDocument()
        })

        it('does not show the editable name input in View mode', () => {
            renderHeader({
                insightMode: ItemMode.View,
                dashboardItemId: SAVED_INSIGHT_ID,
                insight: makeInsight({ user_access_level: AccessControlLevel.Editor }),
            })

            expect(screen.queryByPlaceholderText('Enter name')).not.toBeInTheDocument()
        })
    })

    describe('name editing', () => {
        it('updates the name locally without saving when in Edit mode', async () => {
            const { iLogic } = renderHeader({
                insightMode: ItemMode.Edit,
                dashboardItemId: SAVED_INSIGHT_ID,
                insight: makeInsight({ name: 'Original Name', user_access_level: AccessControlLevel.Editor }),
            })

            const textarea = screen.getByPlaceholderText('Enter name')
            fireEvent.change(textarea, { target: { value: 'New Name' } })

            await waitFor(() => {
                expect(iLogic.values.insight.name).toBe('New Name')
            })
        })

        it('persists the name to the server when changed in View mode', async () => {
            let patchCalled = false
            useMocks({
                post: {
                    '/api/environments/:team_id/query/': () => [200, { results: [] }],
                },
                patch: {
                    '/api/environments/:team_id/insights/:id/': () => {
                        patchCalled = true
                        return [200, makeInsight({ name: 'Updated Name' })]
                    },
                },
            })

            renderHeader({
                insightMode: ItemMode.View,
                dashboardItemId: SAVED_INSIGHT_ID,
                insight: makeInsight({ name: 'Original Name', user_access_level: AccessControlLevel.Editor }),
            })

            // In View mode, the name renders as a button — click to enter editing
            const sceneNameContainer = queryByAttr('scene-name')!
            // eslint-disable-next-line testing-library/no-node-access
            const nameButton = sceneNameContainer.querySelector('button')!
            fireEvent.click(nameButton)

            const textarea = screen.getByPlaceholderText('Enter name')
            fireEvent.change(textarea, { target: { value: 'Updated Name' } })
            fireEvent.blur(textarea)

            await waitFor(() => {
                expect(patchCalled).toBe(true)
            })
        })
    })
})
