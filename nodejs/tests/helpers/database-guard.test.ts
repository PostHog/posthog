import { PostgresRouter, PostgresUse } from '~/common/utils/db/postgres'

import { assertRouterTargetsTestDatabase, assertTestDatabaseName } from './database-guard'

describe('database-guard', () => {
    describe('assertTestDatabaseName', () => {
        it.each(['test_posthog', 'test_persons', 'test_persons_parity', 'test_behavioral_cohorts', 'posthog_test'])(
            'allows test database %s',
            (name) => {
                expect(() => assertTestDatabaseName(name, 'unit test')).not.toThrow()
            }
        )

        it.each([
            'posthog',
            'posthog_persons',
            'behavioral_cohorts',
            'cyclotron',
            'default',
            // "test" embedded in another word must not pass the guard.
            'latest',
            'posthog_latest',
        ])('refuses non-test database %s', (name) => {
            expect(() => assertTestDatabaseName(name, 'unit test')).toThrow(/Refusing to run a destructive test helper/)
        })

        it('includes the database name and source in the error', () => {
            expect(() => assertTestDatabaseName('posthog', 'Postgres COMMON_WRITE')).toThrow(
                expect.objectContaining({
                    message: expect.stringMatching(/"posthog" \(Postgres COMMON_WRITE\)/),
                })
            )
        })
    })

    describe('assertRouterTargetsTestDatabase', () => {
        const routerReturning = (name: string): PostgresRouter =>
            ({
                query: jest.fn().mockResolvedValue({ rows: [{ name }] }),
            }) as unknown as PostgresRouter

        it('passes when the pool connects to a test database', async () => {
            await expect(
                assertRouterTargetsTestDatabase(routerReturning('test_posthog'), PostgresUse.COMMON_WRITE)
            ).resolves.toBeUndefined()
        })

        it('throws when the pool connects to a non-test database', async () => {
            await expect(
                assertRouterTargetsTestDatabase(routerReturning('posthog'), PostgresUse.COMMON_WRITE)
            ).rejects.toThrow(/Refusing to run a destructive test helper/)
        })

        it('names the postgres use in the error', async () => {
            await expect(
                assertRouterTargetsTestDatabase(routerReturning('posthog_persons'), PostgresUse.PERSONS_WRITE)
            ).rejects.toThrow(/Postgres PERSONS_WRITE/)
        })
    })
})
