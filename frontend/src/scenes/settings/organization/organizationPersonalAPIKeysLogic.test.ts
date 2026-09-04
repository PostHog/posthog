import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_PROJECT, MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { OrganizationMembershipLevel } from 'lib/constants'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AvailableFeature, OrganizationType } from '~/types'

import { organizationPersonalAPIKeysLogic } from './organizationPersonalAPIKeysLogic'

const MOCK_KEYS = [
    {
        owner: { first_name: 'Ada', last_name: 'Lovelace', email: 'ada@x.com' },
        mask_value: 'phx_***1234',
        scopes: ['insight:read'],
        access_scope: { type: 'all' },
        last_used_at: null,
        created_at: '2026-01-01T00:00:00Z',
    },
    {
        owner: { first_name: 'Alan', last_name: 'Turing', email: 'alan@x.com' },
        mask_value: 'phx_***5678',
        scopes: ['feature_flag:write'],
        access_scope: { type: 'projects', projects: [{ id: 1, name: 'Default project' }] },
        last_used_at: '2026-02-01T00:00:00Z',
        created_at: '2026-01-15T00:00:00Z',
    },
]

function orgWith(level: OrganizationMembershipLevel, entitled: boolean): OrganizationType {
    return {
        ...MOCK_DEFAULT_ORGANIZATION,
        membership_level: level,
        available_product_features: entitled
            ? [{ key: AvailableFeature.ORGANIZATION_SECURITY_SETTINGS, name: 'Organization security settings' }]
            : [],
    }
}

describe('organizationPersonalAPIKeysLogic', () => {
    let logic: ReturnType<typeof organizationPersonalAPIKeysLogic.build>

    function mountWith(organization: OrganizationType): void {
        initKeaTests(true, MOCK_DEFAULT_TEAM, MOCK_DEFAULT_PROJECT, organization)
        logic = organizationPersonalAPIKeysLogic()
        logic.mount()
    }

    beforeEach(() => {
        useMocks({
            get: {
                '/api/organizations/:organization_id/personal_api_keys/': {
                    count: MOCK_KEYS.length,
                    next: null,
                    previous: null,
                    results: MOCK_KEYS,
                },
            },
        })
    })

    it('loads keys for an admin with the security-settings entitlement', async () => {
        mountWith(orgWith(OrganizationMembershipLevel.Admin, true))
        await expectLogic(logic).toDispatchActions(['loadKeys', 'loadKeysSuccess']).toMatchValues({
            keys: MOCK_KEYS,
            keysLoading: false,
        })
    })

    // The backend rejects this call with a 402 whose body is the raw upsell string; firing it
    // anyway toasts that string on top of the paygate. The gate must keep the request from ever
    // going out when the org is not entitled.
    it('does not load keys when the org lacks the entitlement', async () => {
        mountWith(orgWith(OrganizationMembershipLevel.Admin, false))
        await expectLogic(logic).toNotHaveDispatchedActions(['loadKeys']).toFinishAllListeners()
        expect(logic.values.keys).toEqual([])
        expect(logic.values.keysLoading).toEqual(false)
    })

    // A below-admin member gets a 403 from the same endpoint — gate it out too.
    it('does not load keys for a below-admin member', async () => {
        mountWith(orgWith(OrganizationMembershipLevel.Member, true))
        await expectLogic(logic).toNotHaveDispatchedActions(['loadKeys']).toFinishAllListeners()
        expect(logic.values.keys).toEqual([])
        expect(logic.values.keysLoading).toEqual(false)
    })

    it('filters by owner name, email, or scope', async () => {
        mountWith(orgWith(OrganizationMembershipLevel.Admin, true))
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.setSearch('lovelace')
        expect(logic.values.filteredKeys).toEqual([MOCK_KEYS[0]])

        logic.actions.setSearch('alan@x.com')
        expect(logic.values.filteredKeys).toEqual([MOCK_KEYS[1]])

        logic.actions.setSearch('feature_flag')
        expect(logic.values.filteredKeys).toEqual([MOCK_KEYS[1]])

        logic.actions.setSearch('  ')
        expect(logic.values.filteredKeys).toEqual(MOCK_KEYS)

        logic.actions.setSearch('nomatch')
        expect(logic.values.filteredKeys).toEqual([])
    })
})
