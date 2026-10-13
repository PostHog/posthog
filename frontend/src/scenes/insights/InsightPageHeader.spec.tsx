import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { BindLogic } from 'kea'
import { router } from 'kea-router'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { InsightVizNode, Node, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel, InsightShortId, InsightModel, ItemMode } from '~/types'

import { insightDataLogic } from './insightDataLogic'
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

const SAVED_INSIGHT_ID = 'abc123' as InsightShortId

const MOCK_INSIGHT_BASE: InsightModel = {
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

function makeInsight(overrides: Partial<InsightModel> = {}): InsightModel {
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
            get: {
                // insightLogic mounts alongside and fetches its insight by short_id; without
                // a match it errors with "Insight ... not found"
                '/api/environments/:team_id/insights/': ({ request }: { request: Request }) => [
                    200,
                    {
                        results: [{ id: 1, short_id: new URL(request.url).searchParams.get('short_id'), query: null }],
                    },
                ],
            },
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
        insight?: InsightModel
    }): {
        sceneLogic: ReturnType<typeof insightSceneLogic.build>
        iLogic: ReturnType<typeof insightLogic.build>
    } {
        const { insightMode, dashboardItemId, insight } = opts
        const insightData = insight ?? makeInsight({ user_access_level: AccessControlLevel.Editor })

        const sceneLogic = insightSceneLogic()
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
            <BindLogic logic={insightSceneLogic} props={{}}>
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

    describe('unsaved view-mode edits carried into edit mode', () => {
        // Spying on router.actions.push (rather than asserting post-navigation state) keeps this
        // test at the level of the code the fix actually changed, without booting the fuller
        // router/upgradeQuery chain insightSceneLogic.test.ts already covers.
        let pushSpy: jest.SpyInstance

        beforeEach(() => {
            pushSpy = jest.spyOn(router.actions, 'push').mockImplementation(() => ({ type: 'noop' }) as any)
        })

        afterEach(() => {
            pushSpy.mockRestore()
        })

        function makeTrendsQuery(compare: boolean): InsightVizNode {
            return {
                kind: NodeKind.InsightVizNode,
                source: {
                    kind: NodeKind.TrendsQuery,
                    series: [{ kind: NodeKind.EventsNode, event: '$pageview' }],
                    compareFilter: { compare },
                },
            } as InsightVizNode
        }

        it('includes the current query in the edit URL when it differs from the saved insight', () => {
            const savedQuery = makeTrendsQuery(false)
            const insight = makeInsight({ query: savedQuery })
            renderHeader({ insightMode: ItemMode.View, dashboardItemId: SAVED_INSIGHT_ID, insight })

            // The rendered header already mounted its own insightDataLogic instance — reuse it
            // rather than mounting a second one, which desyncs the reducer state Kea expects.
            const dataLogic = insightDataLogic.findMounted({ dashboardItemId: SAVED_INSIGHT_ID, doNotLoad: true })
            expect(dataLogic).not.toBeNull()

            const modifiedQuery = makeTrendsQuery(true)
            act(() => {
                dataLogic!.actions.setQuery(modifiedQuery)
            })

            fireEvent.click(queryByAttr('insight-edit-button')!)

            expect(pushSpy).toHaveBeenCalledTimes(1)
            const pushedUrl = pushSpy.mock.calls[0][0] as string
            expect(pushedUrl).toContain(`#q=${encodeURIComponent(JSON.stringify(modifiedQuery))}`)
        })

        it('pushes the same edit URL as before when there is nothing unsaved to carry over', () => {
            const savedQuery = makeTrendsQuery(false)
            const insight = makeInsight({ query: savedQuery })
            renderHeader({ insightMode: ItemMode.View, dashboardItemId: SAVED_INSIGHT_ID, insight })

            fireEvent.click(queryByAttr('insight-edit-button')!)

            // No #q= means the editor falls back to loading the saved insight's own query, same as
            // it always has — this asserts the URL is byte-for-byte what insightEdit() alone builds,
            // so the saved query can't have been dropped by this change.
            expect(pushSpy).toHaveBeenCalledTimes(1)
            expect(pushSpy.mock.calls[0][0]).toEqual(urls.insightEdit(SAVED_INSIGHT_ID))
        })
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

    describe('insight context for PostHog AI', () => {
        function findReadDataCall(): Record<string, unknown> | undefined {
            const call = mockUseMaxTool.mock.calls.find(
                (c: Record<string, unknown>[]) => c[0]?.identifier === 'read_data'
            )
            return call?.[0] as Record<string, unknown> | undefined
        }

        it.each([
            {
                scenario: 'saved insight with explicit name',
                insightMode: ItemMode.View,
                dashboardItemId: SAVED_INSIGHT_ID,
                insight: { name: 'My Test Insight', user_access_level: AccessControlLevel.Editor },
                expectedActive: true,
                expectedText: 'My Test Insight',
                expectedContext: { insight_id: 1, insight_short_id: SAVED_INSIGHT_ID },
            },
            {
                scenario: 'saved insight with derived name',
                insightMode: ItemMode.View,
                dashboardItemId: SAVED_INSIGHT_ID,
                insight: {
                    name: undefined,
                    derived_name: 'Pageview count',
                    user_access_level: AccessControlLevel.Editor,
                },
                expectedActive: true,
                expectedText: 'Pageview count',
                expectedContext: { insight_id: 1, insight_short_id: SAVED_INSIGHT_ID },
            },
            {
                scenario: 'unsaved insight',
                insightMode: ItemMode.Edit,
                dashboardItemId: 'new' as const,
                insight: undefined,
                expectedActive: false,
                expectedText: undefined,
                expectedContext: undefined,
            },
        ])(
            '$scenario: active=$expectedActive, text=$expectedText',
            ({ insightMode, dashboardItemId, insight, expectedActive, expectedText, expectedContext }) => {
                renderHeader({
                    insightMode,
                    dashboardItemId,
                    insight: insight ? makeInsight(insight) : undefined,
                })

                const readDataCall = findReadDataCall()
                expect(readDataCall).not.toBeUndefined()
                expect(readDataCall!.active).toBe(expectedActive)

                if (expectedActive) {
                    expect(readDataCall!.contextDescription).toMatchObject({
                        text: expectedText,
                        icon: expect.anything(),
                    })
                    expect(readDataCall!.context).toMatchObject(expectedContext!)
                }
            }
        )
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
            fireEvent.blur(textarea)

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
