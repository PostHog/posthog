import { expectLogic } from 'kea-test-utils'
import { initKeaTests } from '~/test/init'
import { primaryDashboardModalLogic } from './primaryDashboardModalLogic'
import { router } from 'kea-router'
import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'
import { urls } from 'scenes/urls'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'
import { useMocks } from '~/mocks/jest'

describe('primaryDashboardModalLogic', () => {
    let logic: ReturnType<typeof primaryDashboardModalLogic.build>

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
        logic = primaryDashboardModalLogic()
        logic.mount()
    })

    it('modal starts off hidden', async () => {
        await expectLogic(logic).toMatchValues({
            visible: false,
        })
    })
    describe('visible', () => {
        it('can be set to true and false', async () => {
            logic.actions.showPrimaryDashboardModal()
            await expectLogic(logic).toMatchValues({
                visible: true,
            })

            logic.actions.closePrimaryDashboardModal()
            await expectLogic(logic).toMatchValues({
                visible: false,
            })
        })
    })
    describe('primary dashboard id', () => {
        it('is set by setPrimaryDashboard', async () => {
            logic.actions.setPrimaryDashboard(12)
            await expectLogic(logic)
                .toDispatchActions(['setPrimaryDashboard'])
                .toDispatchActions(teamLogic, ['updateCurrentTeam', 'updateCurrentTeamSuccess'])
                .toMatchValues({
                    primaryDashboardId: 12,
                })
        })
    })
})
