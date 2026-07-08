import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { AccountRelationshipApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import { accountRelationshipsLogic } from './accountRelationshipsLogic'

const RELATIONSHIPS_URL = '/api/projects/:team_id/accounts/:account_id/relationships/'

const buildRelationship = (overrides: Partial<AccountRelationshipApi> = {}): AccountRelationshipApi => ({
    id: 'rel-1',
    definition: { id: 'def-1', name: 'CSM', description: null, is_single_holder: true },
    user: { id: 1, email: 'csm@posthog.com' },
    started_at: '2026-01-01T00:00:00Z',
    ended_at: null,
    ...overrides,
})

describe('accountRelationshipsLogic', () => {
    let logic: ReturnType<typeof accountRelationshipsLogic.build>

    beforeEach(() => {
        initKeaTests()
        useMocks({
            get: {
                [RELATIONSHIPS_URL]: [
                    buildRelationship(),
                    buildRelationship({ id: 'rel-2', ended_at: '2026-02-01T00:00:00Z' }),
                ],
            },
        })
        logic = accountRelationshipsLogic({ accountId: 'acc-1' })
        logic.mount()
    })

    it('loads on mount and picks the active assignments for the sidebar summary', async () => {
        await expectLogic(logic).toDispatchActions(['loadRelationships', 'loadRelationshipsSuccess'])
        expect(logic.values.activeRelationships.map((relationship) => relationship.id)).toEqual(['rel-1'])
        expect(logic.values.relationships?.map((relationship) => relationship.id)).toEqual(['rel-1', 'rel-2'])
    })
})
