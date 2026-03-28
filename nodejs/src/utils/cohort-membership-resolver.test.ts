import { CohortMembershipResolver } from './cohort-membership-resolver'
import { PostgresRouter } from './db/postgres'

describe('CohortMembershipResolver', () => {
    let mockPostgres: PostgresRouter
    let resolver: CohortMembershipResolver

    beforeEach(() => {
        mockPostgres = {
            query: jest.fn().mockResolvedValue({ rows: [] }),
        } as unknown as PostgresRouter

        resolver = new CohortMembershipResolver(mockPostgres)
    })

    describe('getPersonCohortIds', () => {
        it('returns empty array when personId is empty string', async () => {
            const result = await resolver.getPersonCohortIds(1, '')
            expect(result).toEqual([])
            expect(mockPostgres.query).not.toHaveBeenCalled()
        })

        it('returns cohort IDs for a person with memberships', async () => {
            ;(mockPostgres.query as jest.Mock).mockResolvedValue({
                rows: [
                    { team_id: 1, person_id: 'person-1', cohort_id: 10 },
                    { team_id: 1, person_id: 'person-1', cohort_id: 20 },
                ],
            })

            const result = await resolver.getPersonCohortIds(1, 'person-1')

            expect(result).toEqual([10, 20])
            expect(mockPostgres.query).toHaveBeenCalledTimes(1)
        })

        it('returns empty array for a person with no memberships', async () => {
            ;(mockPostgres.query as jest.Mock).mockResolvedValue({ rows: [] })

            const result = await resolver.getPersonCohortIds(1, 'person-no-cohorts')

            expect(result).toEqual([])
        })

        it('batches concurrent calls into a single query', async () => {
            ;(mockPostgres.query as jest.Mock).mockResolvedValue({
                rows: [
                    { team_id: 1, person_id: 'person-a', cohort_id: 10 },
                    { team_id: 1, person_id: 'person-b', cohort_id: 20 },
                    { team_id: 1, person_id: 'person-b', cohort_id: 30 },
                ],
            })

            const [resultA, resultB] = await Promise.all([
                resolver.getPersonCohortIds(1, 'person-a'),
                resolver.getPersonCohortIds(1, 'person-b'),
            ])

            expect(resultA).toEqual([10])
            expect(resultB).toEqual([20, 30])
            expect(mockPostgres.query).toHaveBeenCalledTimes(1)

            const callArgs = (mockPostgres.query as jest.Mock).mock.calls[0]
            expect(callArgs[2]).toEqual([
                [1, 1],
                ['person-a', 'person-b'],
            ])
        })

        it('handles multiple teams correctly', async () => {
            ;(mockPostgres.query as jest.Mock).mockResolvedValue({
                rows: [
                    { team_id: 1, person_id: 'person-1', cohort_id: 10 },
                    { team_id: 2, person_id: 'person-1', cohort_id: 50 },
                ],
            })

            const [result1, result2] = await Promise.all([
                resolver.getPersonCohortIds(1, 'person-1'),
                resolver.getPersonCohortIds(2, 'person-1'),
            ])

            expect(result1).toEqual([10])
            expect(result2).toEqual([50])
        })
    })
})
