import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_TEAM, MOCK_DEFAULT_USER } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { TeamType } from '~/types'

import { teamSettingToggleLogic } from './teamSettingToggleLogic'

describe('teamSettingToggleLogic', () => {
    let logic: ReturnType<typeof teamSettingToggleLogic.build>
    let failUpdate = false

    const mountWithServerValue = (anonymizeIps: boolean): void => {
        teamLogic.mount()
        teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, anonymize_ips: anonymizeIps })
        logic = teamSettingToggleLogic({ field: 'anonymize_ips', label: 'Discard client IP data' })
        logic.mount()
    }

    beforeEach(() => {
        failUpdate = false
        useMocks({
            get: {
                '/api/organizations/@current': MOCK_DEFAULT_ORGANIZATION,
                '/api/users/@me/': MOCK_DEFAULT_USER,
            },
            patch: {
                [`/api/environments/${MOCK_DEFAULT_TEAM.id}`]: async ({ request }) => {
                    if (failUpdate) {
                        return [400, { detail: 'nope' }]
                    }
                    const payload = (await request.json()) as Partial<TeamType>
                    return [200, { ...MOCK_DEFAULT_TEAM, ...payload }]
                },
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('flips to the picked value and enters a saving state before the request resolves', () => {
        mountWithServerValue(false)

        logic.actions.setValue(true)

        // Asserted synchronously so we capture the in-flight state before the mocked PATCH resolves.
        expect(logic.values.checked).toBe(true)
        expect(logic.values.optimisticValue).toBe(true)
        expect(logic.values.isSaving).toBe(true)
    })

    it('settles onto the server value once the update succeeds', async () => {
        mountWithServerValue(false)

        logic.actions.setValue(true)
        await expectLogic(logic)
            .toDispatchActions(['updateCurrentTeamSuccess', 'settle'])
            .toMatchValues({ checked: true, optimisticValue: null, isSaving: false })
    })

    it('reverts to the server value and stops saving when the update fails', async () => {
        failUpdate = true
        mountWithServerValue(false)

        logic.actions.setValue(true)
        await expectLogic(logic)
            .toDispatchActions(['updateCurrentTeamFailure', 'revert'])
            .toMatchValues({ checked: false, optimisticValue: null, isSaving: false })
    })
})
