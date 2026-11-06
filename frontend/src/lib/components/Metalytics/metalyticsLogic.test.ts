import api from 'lib/api'

import { sidePanelContextLogic } from '~/layout/navigation-3000/sidepanel/sidePanelContextLogic'
import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { sceneLayoutLogic } from '~/layout/scenes/sceneLayoutLogic'
import { initKeaTests } from '~/test/init'
import { expectLogic } from '~/test/keaTestUtils'
import { ActivityScope, SidePanelTab } from '~/types'

import { metalyticsLogic } from './metalyticsLogic'

describe('metalyticsLogic', () => {
    beforeEach(() => {
        initKeaTests()
        sidePanelContextLogic.mount()
        jest.spyOn(sidePanelContextLogic.selectors, 'sceneSidePanelContext').mockReturnValue({
            activity_scope: ActivityScope.INSIGHT,
            activity_item_id: 'insight1',
        })
        jest.spyOn(api, 'queryHogQL').mockResolvedValue({ results: [] })
        jest.spyOn(api, 'create').mockResolvedValue({})
        sceneLayoutLogic.mount()
    })

    afterEach(() => jest.restoreAllMocks())

    it.each(['inline', 'actions', 'activity'] as const)(
        'defers statistics until the %s sidebar opens, including subsequent insight navigation',
        async (panel) => {
            const logic = metalyticsLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            expect(api.queryHogQL).not.toHaveBeenCalled()
            expect(api.create).toHaveBeenCalledWith(expect.stringContaining('/metalytics/'), {
                metric_name: 'viewed',
                instance_id: 'Insight:insight1',
            })

            await expectLogic(logic, () => {
                if (panel === 'inline') {
                    sceneLayoutLogic.actions.setScenePanelOpen(true)
                } else {
                    sidePanelStateLogic.actions.openSidePanel(
                        panel === 'actions' ? SidePanelTab.Info : SidePanelTab.Activity
                    )
                }
            }).toFinishAllListeners()
            expect(api.queryHogQL).toHaveBeenCalledTimes(2)

            await expectLogic(logic, () => {
                jest.mocked(sidePanelContextLogic.selectors.sceneSidePanelContext).mockReturnValue({
                    activity_scope: ActivityScope.INSIGHT,
                    activity_item_id: 'insight2',
                })
                sceneLayoutLogic.actions.setScenePanelIsPresent(true)
            }).toFinishAllListeners()
            expect(api.queryHogQL).toHaveBeenCalledTimes(4)
            expect(
                jest
                    .mocked(api.queryHogQL)
                    .mock.calls.slice(2)
                    .every(([query]) => query.includes('Insight:insight2'))
            ).toBe(true)

            sceneLayoutLogic.actions.setScenePanelOpen(false)
            sidePanelStateLogic.actions.closeSidePanel()
            await expectLogic(logic, () => {
                jest.mocked(sidePanelContextLogic.selectors.sceneSidePanelContext).mockReturnValue({
                    activity_scope: ActivityScope.INSIGHT,
                    activity_item_id: 'insight3',
                })
                sceneLayoutLogic.actions.setScenePanelIsPresent(true)
            }).toFinishAllListeners()
            expect(api.queryHogQL).toHaveBeenCalledTimes(4)
        }
    )

    it('loads statistics when the insight mounts with the sidebar already open', async () => {
        sceneLayoutLogic.actions.setScenePanelOpen(true)
        const logic = metalyticsLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(api.queryHogQL).toHaveBeenCalledTimes(2)
    })

    it('clears loaded statistics when the panel closes before navigating', async () => {
        jest.mocked(api.queryHogQL)
            .mockResolvedValueOnce({ results: [[10, 2]] })
            .mockResolvedValueOnce({ results: [['previous-user']] })
        sceneLayoutLogic.actions.setScenePanelOpen(true)
        const logic = metalyticsLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.viewCount).toEqual({ views: 10, users: 2 })
        expect(logic.values.recentUsers).toEqual(['previous-user'])

        await expectLogic(logic, () => {
            sceneLayoutLogic.actions.setScenePanelOpen(false)
        }).toFinishAllListeners()
        await expectLogic(logic, () => {
            jest.mocked(sidePanelContextLogic.selectors.sceneSidePanelContext).mockReturnValue({
                activity_scope: ActivityScope.INSIGHT,
                activity_item_id: 'insight2',
            })
            sceneLayoutLogic.actions.setScenePanelIsPresent(true)
        })
            .toFinishAllListeners()
            .toMatchValues({ viewCount: null, recentUsers: [], viewCountLoading: false, recentUsersLoading: false })
        expect(api.queryHogQL).toHaveBeenCalledTimes(2)
    })

    it.each([true, false])('discards older responses after navigation with panel open=%s', async (panelOpen) => {
        let resolveOldCount!: () => void
        let resolveOldUsers!: () => void
        jest.mocked(api.queryHogQL)
            .mockImplementationOnce(
                () => new Promise((resolve) => (resolveOldCount = () => resolve({ results: [[100, 10]] })))
            )
            .mockImplementationOnce(
                () => new Promise((resolve) => (resolveOldUsers = () => resolve({ results: [['previous-user']] })))
            )
            .mockResolvedValueOnce({ results: [[20, 3]] })
            .mockResolvedValueOnce({ results: [['current-user']] })
        sceneLayoutLogic.actions.setScenePanelOpen(true)
        const logic = metalyticsLogic()
        logic.mount()
        expect(api.queryHogQL).toHaveBeenCalledTimes(2)

        await expectLogic(logic, () => {
            if (!panelOpen) {
                sceneLayoutLogic.actions.setScenePanelOpen(false)
            }
            jest.mocked(sidePanelContextLogic.selectors.sceneSidePanelContext).mockReturnValue({
                activity_scope: ActivityScope.INSIGHT,
                activity_item_id: 'insight2',
            })
            sceneLayoutLogic.actions.setScenePanelIsPresent(true)
        }).toDispatchActions(['loadViewCountSuccess', 'loadUsersLast30daysSuccess'])

        await expectLogic(logic, () => {
            resolveOldCount()
            resolveOldUsers()
        })
            .toFinishAllListeners()
            .toMatchValues({
                viewCount: panelOpen ? { views: 20, users: 3 } : null,
                recentUsers: panelOpen ? ['current-user'] : [],
                viewCountLoading: false,
                recentUsersLoading: false,
            })
        expect(api.queryHogQL).toHaveBeenCalledTimes(panelOpen ? 4 : 2)
    })
})
