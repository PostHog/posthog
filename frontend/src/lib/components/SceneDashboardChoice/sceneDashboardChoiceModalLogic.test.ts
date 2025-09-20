import { MOCK_DEFAULT_TEAM, MOCK_DEFAULT_USER } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { Scene } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { sceneDashboardChoiceModalLogic } from './sceneDashboardChoiceModalLogic'

describe('sceneDashboardChoiceModalLogic', () => {
    let logic: ReturnType<typeof sceneDashboardChoiceModalLogic.build>

    beforeEach(async () => {
        useMocks({
            get: {
                '/api/projects/@current': () => MOCK_DEFAULT_TEAM,
            },
            post: {
                '/api/users/@me/scene_personalisation': (req) => {
                    const data = req.body as any
                    return [
                        200,
                        {
                            ...MOCK_DEFAULT_USER,
                            scene_personalisation: [
                                ...(MOCK_DEFAULT_USER.scene_personalisation || []),
                                { scene: data.scene, dashboard: data.dashboard },
                            ],
                        },
                    ]
                },
            },
            patch: {
                '/api/environments/:team': (req) => {
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
        await expectLogic(userLogic).toDispatchActions(['loadUserSuccess']).toFinishAllListeners()
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
                .toDispatchActions(userLogic, ['setUserScenePersonalisation', 'setUserScenePersonalisationSuccess'])
                .toMatchValues({
                    currentDashboardId: 12,
                })
        })
    })
})
