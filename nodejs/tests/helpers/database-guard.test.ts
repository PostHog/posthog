import { PostgresRouter, PostgresUse } from '../../src/utils/db/postgres'
import {
    UNSAFE_DATABASE_RESET_ENV_VAR,
    assertRouterTargetsTestDatabase,
    assertTestDatabaseName,
} from './database-guard'

describe('database-guard', () => {
    const emptyEnv = {}

    describe('assertTestDatabaseName', () => {
        it.each(['test_posthog', 'test_persons', 'test_persons_parity', 'test_behavioral_cohorts', 'posthog_test'])(
            'allows test database %s',
            (name) => {
                expect(() => assertTestDatabaseName(name, 'unit test', emptyEnv)).not.toThrow()
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
            expect(() => assertTestDatabaseName(name, 'unit test', emptyEnv)).toThrow(
                /Refusing to run a destructive test helper/
            )
        })

        it('includes the database name, source and escape hatch in the error', () => {
            expect(() => assertTestDatabaseName('posthog', 'Postgres COMMON_WRITE', emptyEnv)).toThrow(
                expect.objectContaining({
                    message: expect.stringMatching(
                        /"posthog" \(Postgres COMMON_WRITE\)[\s\S]*ALLOW_NON_TEST_DATABASE_RESET=1/
                    ),
                })
            )
        })

        it.each(['1', 'true', 'TRUE', 'yes'])('allows non-test databases when the escape hatch is %s', (value) => {
            const env = { [UNSAFE_DATABASE_RESET_ENV_VAR]: value }
            expect(() => assertTestDatabaseName('posthog', 'unit test', env)).not.toThrow()
        })

        it.each(['0', 'false', 'no', ''])('keeps the guard active when the escape hatch is %s', (value) => {
            const env = { [UNSAFE_DATABASE_RESET_ENV_VAR]: value }
            expect(() => assertTestDatabaseName('posthog', 'unit test', env)).toThrow(
                /Refusing to run a destructive test helper/
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
                assertRouterTargetsTestDatabase(routerReturning('test_posthog'), PostgresUse.COMMON_WRITE, emptyEnv)
            ).resolves.toBeUndefined()
        })

        it('throws when the pool connects to a non-test database', async () => {
            await expect(
                assertRouterTargetsTestDatabase(routerReturning('posthog'), PostgresUse.COMMON_WRITE, emptyEnv)
            ).rejects.toThrow(/Refusing to run a destructive test helper/)
        })

        it('names the postgres use in the error', async () => {
            await expect(
                assertRouterTargetsTestDatabase(routerReturning('posthog_persons'), PostgresUse.PERSONS_WRITE, emptyEnv)
            ).rejects.toThrow(/Postgres PERSONS_WRITE/)
        })
    })
})
