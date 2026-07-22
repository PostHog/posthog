import { PostgresUse } from '~/common/utils/db/postgres'

import { CohortMembershipService } from './cohort-membership.service'

describe('CohortMembershipService', () => {
    let query: jest.Mock
    let service: CohortMembershipService

    beforeEach(() => {
        query = jest.fn()
        service = new CohortMembershipService({ query } as any)
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    it('maps returned rows to membership and missing rows to non-membership', async () => {
        query.mockResolvedValue({ rows: [{ cohort_id: 1 }] })

        const result = await service.fetchMemberships(2, 'person-uuid', [1, 2])

        expect(result).toEqual(
            new Map([
                [1, true],
                [2, false],
            ])
        )
        expect(query).toHaveBeenCalledWith(
            PostgresUse.BEHAVIORAL_COHORTS_RW,
            expect.stringContaining('in_cohort = true'),
            [2, 'person-uuid', [1, 2]],
            'fetchHogFlowCohortMemberships'
        )
    })

    it('serves repeat lookups from cache and only queries uncached cohort ids', async () => {
        query.mockResolvedValue({ rows: [{ cohort_id: 1 }] })
        await service.fetchMemberships(2, 'person-uuid', [1])

        const second = await service.fetchMemberships(2, 'person-uuid', [1])
        expect(query).toHaveBeenCalledTimes(1)
        expect(second.get(1)).toBe(true)

        query.mockResolvedValue({ rows: [] })
        const third = await service.fetchMemberships(2, 'person-uuid', [1, 3])
        expect(query).toHaveBeenCalledTimes(2)
        expect(query).toHaveBeenLastCalledWith(
            expect.anything(),
            expect.anything(),
            [2, 'person-uuid', [3]],
            expect.anything()
        )
        expect(third).toEqual(
            new Map([
                [1, true],
                [3, false],
            ])
        )
    })

    it('throws on query error instead of returning empty membership', async () => {
        // An empty result would make notInCohort wrongly evaluate to true — errors must propagate
        query.mockRejectedValue(new Error('db down'))

        await expect(service.fetchMemberships(2, 'person-uuid', [1])).rejects.toThrow('db down')
    })

    it('throws when the lookup exceeds the timeout', async () => {
        jest.useFakeTimers()
        query.mockImplementation(() => new Promise(() => {}))

        const promise = service.fetchMemberships(2, 'person-uuid', [1])
        const assertion = expect(promise).rejects.toThrow('timed out')
        jest.advanceTimersByTime(1001)
        await assertion
    })
})
