import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import type { UserBasicType } from '~/types'

import type {
    AccountRelationshipApi,
    AccountRelationshipDefinitionApi,
} from 'products/customer_analytics/frontend/generated/api.schemas'

import { accountRelationshipsLogic } from './accountRelationshipsLogic'

const RELATIONSHIPS_URL = '/api/projects/:team_id/accounts/:account_id/relationships/'

const CSM: AccountRelationshipDefinitionApi = { id: 'def-1', name: 'CSM', description: null, is_single_holder: true }
const AE: AccountRelationshipDefinitionApi = {
    id: 'def-2',
    name: 'Account executive',
    description: null,
    is_single_holder: true,
}

const buildRelationship = (overrides: Partial<AccountRelationshipApi> = {}): AccountRelationshipApi => ({
    id: 'rel-1',
    definition: CSM,
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
                    buildRelationship({ id: 'rel-3', definition: AE, started_at: '2026-03-01T00:00:00Z' }),
                ],
            },
        })
        logic = accountRelationshipsLogic({ accountId: 'acc-1' })
        logic.mount()
    })

    it('loads on mount and picks the active assignments for the sidebar summary', async () => {
        await expectLogic(logic).toDispatchActions(['loadRelationships', 'loadRelationshipsSuccess'])
        expect(logic.values.activeRelationships.map((relationship) => relationship.id)).toEqual(['rel-1', 'rel-3'])
        expect(logic.values.relationships?.map((relationship) => relationship.id)).toEqual(['rel-1', 'rel-2', 'rel-3'])
    })

    it('shows current assignments on top (newest first) and narrows by definition', async () => {
        await expectLogic(logic).toDispatchActions(['loadRelationshipsSuccess'])
        expect(logic.values.displayedRelationships.map((relationship) => relationship.id)).toEqual([
            'rel-3',
            'rel-1',
            'rel-2',
        ])

        logic.actions.setDefinitionFilter(CSM.id)
        expect(logic.values.displayedRelationships.map((relationship) => relationship.id)).toEqual(['rel-1', 'rel-2'])
        expect(logic.values.definitionFilterOptions.map((definition) => definition.name)).toEqual([
            'Account executive',
            'CSM',
        ])
    })

    it('assigning posts the definition and user, then reloads the timeline', async () => {
        let postedBody: Record<string, unknown> | null = null
        useMocks({
            post: {
                [RELATIONSHIPS_URL]: async ({ request }) => {
                    postedBody = (await request.json()) as Record<string, unknown>
                    return [
                        201,
                        buildRelationship({ id: 'rel-new', definition: AE, user: { id: 7, email: 'ae@posthog.com' } }),
                    ]
                },
            },
        })

        logic.actions.assignRelationship(AE, { id: 7 } as UserBasicType)
        await expectLogic(logic).toDispatchActions([
            'relationshipSaveStarted',
            'loadRelationships',
            'relationshipSaveFinished',
        ])
        expect(postedBody).toEqual({ definition: AE.id, user: 7 })
    })
})
