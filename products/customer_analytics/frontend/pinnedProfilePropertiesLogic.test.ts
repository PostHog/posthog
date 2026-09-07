import { expectLogic } from 'kea-test-utils'

import { userPreferencesLogic } from 'lib/logic/userPreferencesLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { CustomerProfileConfigType, CustomerProfileScope } from '~/types'

import { pinnedProfilePropertiesLogic } from './pinnedProfilePropertiesLogic'

const CONFIGS_URL = '/api/environments/:team_id/customer_profile_configs/'
const CONFIG_URL = '/api/environments/:team_id/customer_profile_configs/:id/'

const teamConfig = (pinned_properties: string[]): CustomerProfileConfigType => ({
    id: 'config-1',
    team: 997,
    content: [],
    sidebar: [],
    pinned_properties,
    scope: CustomerProfileScope.PERSON,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
})

describe('pinnedProfilePropertiesLogic', () => {
    let logic: ReturnType<typeof pinnedProfilePropertiesLogic.build>
    let patchedBodies: Record<string, any>[]

    const mocksFor = (pinned_properties: string[] | null): Parameters<typeof useMocks>[0] => ({
        get: {
            [CONFIGS_URL]: {
                count: pinned_properties === null ? 0 : 1,
                results: pinned_properties === null ? [] : [teamConfig(pinned_properties)],
            },
        },
        patch: {
            [CONFIG_URL]: async ({ request }) => {
                const body = (await request.json()) as Record<string, any>
                patchedBodies.push(body)
                return [200, teamConfig(body.pinned_properties)]
            },
        },
    })

    const mount = async (): Promise<void> => {
        logic = pinnedProfilePropertiesLogic({ scope: CustomerProfileScope.PERSON })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    }

    beforeEach(() => {
        initKeaTests()
        localStorage.clear()
        patchedBodies = []
    })

    afterEach(() => {
        logic?.unmount()
        localStorage.clear()
    })

    it('shows the team default to somebody who has pinned nothing', async () => {
        useMocks(mocksFor(['plan', 'arr']))
        await mount()

        expect(logic.values.pinnedProperties).toEqual(['plan', 'arr'])
        expect(logic.values.hasOwnPins).toBe(false)
    })

    it('falls back to the seeded defaults when the team has no default', async () => {
        useMocks(mocksFor(null))
        await mount()

        expect(logic.values.teamPinnedProperties).toBeNull()
        expect(logic.values.pinnedProperties).toEqual(userPreferencesLogic.values.defaultPinnedPersonProperties)
    })

    it('pins on top of the team default without dropping it', async () => {
        useMocks(mocksFor(['plan', 'arr']))
        await mount()

        logic.actions.pinProperty('email')

        expect(logic.values.pinnedProperties).toEqual(['plan', 'arr', 'email'])
        expect(logic.values.hasOwnPins).toBe(true)
    })

    it('goes back to the team default after use team default', async () => {
        useMocks(mocksFor(['plan', 'arr']))
        await mount()
        logic.actions.unpinProperty('plan')
        expect(logic.values.pinnedProperties).toEqual(['arr'])

        logic.actions.useTeamDefault()

        expect(logic.values.pinnedProperties).toEqual(['plan', 'arr'])
    })

    it('shares the pins a person sees with the whole team', async () => {
        useMocks(mocksFor(['plan']))
        await mount()
        logic.actions.pinProperty('arr')

        logic.actions.setAsTeamDefault()
        await expectLogic(logic).toFinishAllListeners()

        expect(patchedBodies).toEqual([{ pinned_properties: ['plan', 'arr'] }])
    })
})
