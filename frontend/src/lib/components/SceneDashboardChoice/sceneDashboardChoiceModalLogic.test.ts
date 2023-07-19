import { expectLogic } from 'kea-test-utils'
import { initKeaTests } from '~/test/init'
import { sceneDashboardChoiceModalLogic } from './sceneDashboardChoiceModalLogic'
import { router } from 'kea-router'
import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'
import { urls } from 'scenes/urls'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'
import { useMocks } from '~/mocks/jest'

describe('sceneDashboardChoiceModalLogic', () => {
    let logic: ReturnType<typeof sceneDashboardChoiceModalLogic.build>

    beforeEach(async () => {
        useMocks({
            patch: {
                '/api/projects/:team': (req) => {
                    const data = req.body as any
                    return [200, { ...MOCK_DEFAULT_TEAM, primary_dashboard: data?.primary_dashboard }]
                },
            },
        })
        initKeaTests()
        userLogic.mount()
        await expectLogic(teamLogic).toDispatchActions(['loadCurrentTeamSuccess'])
        router.actions.push(urls.projectHomepage())
        logic = sceneDashboardChoiceModalLogic()
        logic.mount()
    })

    it('modal starts off hidden', async () => {
        await expectLogic(logic).toMatchValues({
            isOpen: false,
        })
    })
    describe('isOpen', () => {
        it('can be set to true and false', async () => {
            logic.actions.showSceneDashboardChoiceModal()
            await expectLogic(logic).toMatchValues({
                isOpen: true,
            })

            logic.actions.closeSceneDashboardChoiceModal()
            await expectLogic(logic).toMatchValues({
                isOpen: false,
            })
        })
    })
    describe('primary dashboard id', () => {
        it('is set by setSceneDashboardChoice', async () => {
            logic.actions.setSceneDashboardChoice(12)
            await expectLogic(logic)
                .toDispatchActions(['setSceneDashboardChoice'])
                .toDispatchActions(teamLogic, ['updateCurrentTeam', 'updateCurrentTeamSuccess'])
                .toMatchValues({
                    primaryDashboardId: 12,
                })
        })
    })
})
