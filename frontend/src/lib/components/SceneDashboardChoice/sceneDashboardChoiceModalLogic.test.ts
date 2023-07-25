import { expectLogic } from 'kea-test-utils'
import { initKeaTests } from '~/test/init'
import { sceneDashboardChoiceModalLogic } from './sceneDashboardChoiceModalLogic'
import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'
import { useMocks } from '~/mocks/jest'
import { Scene } from 'scenes/sceneTypes'

describe('sceneDashboardChoiceModalLogic ', () => {
    let logic: ReturnType<typeof sceneDashboardChoiceModalLogic.build>

    beforeEach(async () => {
        useMocks({
            patch: {
                '/api/projects/:team': (req) => {
                    const data = req.body as any
                    return [
                        200,
                        {
                            ...MOCK_DEFAULT_TEAM,
                            primary_dashboard: data?.primary_dashboard,
                        },
                    ]
                },
            },
        })
        initKeaTests()
        userLogic.mount()
        await expectLogic(teamLogic).toDispatchActions(['loadCurrentTeamSuccess'])
    })

    describe('for project homepage', () => {
        beforeEach(() => {
            logic = sceneDashboardChoiceModalLogic({ scene: Scene.ProjectHomepage })
            logic.mount()
        })

        it('modal starts off hidden', async () => {
            await expectLogic(logic).toMatchValues({
                isOpen: false,
            })
        })

        it('can be opened and closed', async () => {
            await expectLogic(logic, () => {
                logic.actions.showSceneDashboardChoiceModal()
            }).toMatchValues({
                isOpen: true,
            })

            logic.actions.closeSceneDashboardChoiceModal()
            await expectLogic(logic).toMatchValues({
                isOpen: false,
            })
        })

        it('is set by setSceneDashboardChoice', async () => {
            await expectLogic(logic, () => {
                logic.actions.setSceneDashboardChoice(12)
            })
                .toDispatchActions(teamLogic, ['updateCurrentTeam', 'updateCurrentTeamSuccess'])
                .toMatchValues({
                    currentDashboardId: 12,
                })
        })
    })

    describe('for person page', () => {
        beforeEach(() => {
            logic = sceneDashboardChoiceModalLogic({ scene: Scene.Person })
            logic.mount()
        })

        it('choice is set by setSceneDashboardChoice', async () => {
            await expectLogic(logic, () => {
                logic.actions.setSceneDashboardChoice(12)
            })
                .toDispatchActions(teamLogic, ['updateCurrentTeam', 'updateCurrentTeamSuccess'])
                .toMatchValues({
                    currentDashboardId: 12,
                })
        })
    })
})
