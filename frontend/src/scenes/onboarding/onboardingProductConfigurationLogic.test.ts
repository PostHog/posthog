import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { OrganizationMembershipLevel } from 'lib/constants'
import { teamLogic } from 'scenes/teamLogic'

import { initKeaTests } from '~/test/init'

import { ProductConfigOption, onboardingProductConfigurationLogic } from './onboardingProductConfigurationLogic'

const toggle = (teamProperty: ProductConfigOption['teamProperty'], value: boolean): ProductConfigOption => ({
    title: teamProperty,
    description: '',
    teamProperty,
    value,
    type: 'toggle',
    visible: true,
})

describe('onboardingProductConfigurationLogic', () => {
    let logic: ReturnType<typeof onboardingProductConfigurationLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = onboardingProductConfigurationLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it.each([
        {
            role: 'member',
            access: { effective_membership_level: OrganizationMembershipLevel.Member, user_access_level: 'member' },
            expected: { session_recording_opt_in: true },
        },
        {
            role: 'admin',
            access: { effective_membership_level: OrganizationMembershipLevel.Member, user_access_level: 'admin' },
            expected: { session_recording_opt_in: true, capture_console_log_opt_in: true, heatmaps_opt_in: true },
        },
    ])('saves only the team fields a project $role can edit', async ({ access, expected }) => {
        teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, ...access } as any)
        logic.actions.setConfigOptions([
            toggle('session_recording_opt_in', true),
            toggle('capture_console_log_opt_in', true),
            toggle('heatmaps_opt_in', true),
        ])

        await expectLogic(logic, () => {
            logic.actions.saveConfiguration()
        }).toDispatchActions([teamLogic.actionCreators.updateCurrentTeam(expected)])
    })
})
