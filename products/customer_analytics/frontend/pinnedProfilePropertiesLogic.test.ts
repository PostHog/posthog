import { expectLogic } from 'kea-test-utils'

import { userPreferencesLogic } from 'lib/logic/userPreferencesLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { CustomerProfileConfigType, CustomerProfileScope } from '~/types'

import { pinnedProfilePropertiesLogic } from './pinnedProfilePropertiesLogic'

const CONFIGS_URL = '/api/environments/:team_id/customer_profile_configs/'
const CONFIG_URL = '/api/environments/:team_id/customer_profile_configs/:id/'

// Group pins made before they were kept per group type live under the key kea-localstorage
// derives from the reducer's path.
const LEGACY_GROUP_PINS_KEY = 'lib.logic.userPreferencesLogic.pinnedGroupProperties'

const teamConfig = (
    pinned_properties: string[],
    scope: CustomerProfileScope = CustomerProfileScope.PERSON
): CustomerProfileConfigType => ({
    id: `config-${scope}`,
    team: 997,
    content: [],
    sidebar: [],
    pinned_properties,
    scope,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
})

type BuiltLogic = ReturnType<typeof pinnedProfilePropertiesLogic.build>

describe('pinnedProfilePropertiesLogic', () => {
    let mounted: BuiltLogic[]
    let patchedBodies: Record<string, any>[]

    const mocksForScopes = (
        pinnedByScope: Partial<Record<CustomerProfileScope, string[]>>
    ): Parameters<typeof useMocks>[0] => ({
        get: {
            [CONFIGS_URL]: ({ request }) => {
                const scope = new URL(request.url).searchParams.get('scope') as CustomerProfileScope
                const pinned_properties = pinnedByScope[scope]
                const results = pinned_properties ? [teamConfig(pinned_properties, scope)] : []
                return { count: results.length, results }
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

    const mocksFor = (pinned_properties: string[] | null): Parameters<typeof useMocks>[0] =>
        mocksForScopes(pinned_properties === null ? {} : { [CustomerProfileScope.PERSON]: pinned_properties })

    const mount = async (scope: CustomerProfileScope = CustomerProfileScope.PERSON): Promise<BuiltLogic> => {
        const logic = pinnedProfilePropertiesLogic({ scope })
        logic.mount()
        mounted.push(logic)
        await expectLogic(logic).toFinishAllListeners()
        return logic
    }

    beforeEach(() => {
        initKeaTests()
        localStorage.clear()
        mounted = []
        patchedBodies = []
    })

    afterEach(() => {
        mounted.forEach((logic) => logic.unmount())
        localStorage.clear()
    })

    it('shows the team default to somebody who has pinned nothing', async () => {
        useMocks(mocksFor(['plan', 'arr']))
        const logic = await mount()

        expect(logic.values.pinnedProperties).toEqual(['plan', 'arr'])
        expect(logic.values.hasOwnPins).toBe(false)
    })

    it('falls back to the seeded defaults when the team has no default', async () => {
        useMocks(mocksFor(null))
        const logic = await mount()

        expect(logic.values.teamPinnedProperties).toBeNull()
        expect(logic.values.pinnedProperties).toEqual(userPreferencesLogic.values.defaultPinnedPersonProperties)
    })

    it('pins on top of the team default without dropping it', async () => {
        useMocks(mocksFor(['plan', 'arr']))
        const logic = await mount()

        logic.actions.pinProperty('email')

        expect(logic.values.pinnedProperties).toEqual(['plan', 'arr', 'email'])
        expect(logic.values.hasOwnPins).toBe(true)
    })

    it('goes back to the team default after use team default', async () => {
        useMocks(mocksFor(['plan', 'arr']))
        const logic = await mount()
        logic.actions.unpinProperty('plan')
        expect(logic.values.pinnedProperties).toEqual(['arr'])

        logic.actions.useTeamDefault()

        expect(logic.values.pinnedProperties).toEqual(['plan', 'arr'])
    })

    it('shares the pins a person sees with the whole team', async () => {
        useMocks(mocksFor(['plan']))
        const logic = await mount()
        logic.actions.pinProperty('arr')

        logic.actions.setAsTeamDefault()
        await expectLogic(logic).toFinishAllListeners()

        expect(patchedBodies).toEqual([{ pinned_properties: ['plan', 'arr'] }])
    })

    it('keeps the pins of one group type apart from another', async () => {
        useMocks(
            mocksForScopes({
                [CustomerProfileScope.GROUP_0]: ['name', 'plan'],
                [CustomerProfileScope.GROUP_1]: ['name', 'tier'],
            })
        )
        const companies = await mount(CustomerProfileScope.GROUP_0)
        const organizations = await mount(CustomerProfileScope.GROUP_1)

        companies.actions.pinProperty('arr')

        expect(companies.values.pinnedProperties).toEqual(['name', 'plan', 'arr'])
        expect(organizations.values.pinnedProperties).toEqual(['name', 'tier'])
        expect(organizations.values.hasOwnPins).toBe(false)

        organizations.actions.pinProperty('seats')
        organizations.actions.useTeamDefault()

        expect(organizations.values.pinnedProperties).toEqual(['name', 'tier'])
        expect(companies.values.pinnedProperties).toEqual(['name', 'plan', 'arr'])
    })

    it('still shows group pins made before they were kept per group type', async () => {
        localStorage.setItem(LEGACY_GROUP_PINS_KEY, JSON.stringify(['name', 'industry']))
        useMocks(mocksForScopes({ [CustomerProfileScope.GROUP_0]: ['name', 'plan'] }))

        const companies = await mount(CustomerProfileScope.GROUP_0)

        expect(companies.values.pinnedProperties).toEqual(['name', 'industry'])
    })
})
