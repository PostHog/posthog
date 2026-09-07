import { deserializeResolverState, serializeResolverState } from './batch-resolver.types'

describe('BatchResolverState serialization', () => {
    it('round-trips account audience filters (zod strips unknown keys, so a missed schema field would vanish)', () => {
        const state = {
            batchJobId: 'job-1',
            teamId: 1,
            hogFlowId: 'flow-1',
            filters: {
                audience_type: 'accounts' as const,
                properties: [{ key: 'defn-id', type: 'account_custom_property', operator: 'exact', value: ['x'] }],
                tag_names: ['vip'],
                assigned_to_user_ids: [7],
                all_roles_unassigned: true,
            },
            variables: {},
            maxAudienceSize: 100,
            cursor: null,
            totalEnqueued: 0,
            pagesProcessed: 0,
            attempts: 0,
            startedAt: '2026-01-01T00:00:00.000Z',
        }

        expect(deserializeResolverState(serializeResolverState(state))).toEqual(state)
    })
})
