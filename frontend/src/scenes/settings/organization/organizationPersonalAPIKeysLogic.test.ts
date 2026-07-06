import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

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

describe('organizationPersonalAPIKeysLogic', () => {
    let logic: ReturnType<typeof organizationPersonalAPIKeysLogic.build>

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
        initKeaTests()
        logic = organizationPersonalAPIKeysLogic()
        logic.mount()
    })

    it('loads keys on mount', async () => {
        await expectLogic(logic).toDispatchActions(['loadKeys', 'loadKeysSuccess']).toMatchValues({
            keys: MOCK_KEYS,
            keysLoading: false,
        })
    })

    it('starts with empty array and loading state', () => {
        expect(logic.values.keys).toEqual([])
        expect(logic.values.keysLoading).toEqual(true)
    })

    it('filters by owner name, email, or scope', async () => {
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
