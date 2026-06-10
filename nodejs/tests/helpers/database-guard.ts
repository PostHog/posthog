import { PostgresRouter, PostgresUse } from '../../src/utils/db/postgres'

/**
 * Escape hatch for environments whose test database legitimately doesn't have
 * "test" in its name. Set to a truthy value to skip the guard.
 */
export const UNSAFE_DATABASE_RESET_ENV_VAR = 'ALLOW_NON_TEST_DATABASE_RESET'

const TEST_DATABASE_NAME_PATTERN = /test/i

/**
 * Throws unless `databaseName` looks like a test database (contains "test").
 *
 * Destructive test helpers (mass DELETE/TRUNCATE) call this before touching a
 * database, so a misconfigured environment (e.g. NODE_ENV/DEBUG or a
 * DATABASE_URL pointing at the dev `posthog` database leaking in from a shell
 * or IDE) produces a loud error instead of silently wiping real dev data.
 */
export function assertTestDatabaseName(
    databaseName: string,
    source: string,
    env: Record<string, string | undefined> = process.env
): void {
    if (env[UNSAFE_DATABASE_RESET_ENV_VAR]) {
        return
    }
    if (TEST_DATABASE_NAME_PATTERN.test(databaseName)) {
        return
    }
    throw new Error(
        `🛑 Refusing to run a destructive test helper against database "${databaseName}" (${source}).\n\n` +
            `The database name does not contain "test", so it looks like a real development\n` +
            `or production database. Continuing would have deleted data from it.\n\n` +
            `Plugin-server tests expect dedicated test databases (test_posthog, test_persons,\n` +
            `test_behavioral_cohorts on Postgres; posthog_test on ClickHouse). This error\n` +
            `usually means DATABASE_URL, PERSONS_DATABASE_URL, CLICKHOUSE_DATABASE or similar\n` +
            `leaked in from your shell or IDE. Unset them, or create the test databases with\n` +
            `\`pnpm --filter=@posthog/nodejs setup:test\`.\n\n` +
            `If you really do want to wipe "${databaseName}", set ${UNSAFE_DATABASE_RESET_ENV_VAR}=1.`
    )
}

/**
 * Asserts that the database a router's pool actually connects to for the given
 * use is a test database. Queries `current_database()` so the check reflects
 * ground truth regardless of how the connection URL was assembled.
 */
export async function assertRouterTargetsTestDatabase(
    router: PostgresRouter,
    use: PostgresUse,
    env: Record<string, string | undefined> = process.env
): Promise<void> {
    const result = await router.query<{ name: string }>(
        use,
        'SELECT current_database() AS name',
        undefined,
        'database-guard'
    )
    assertTestDatabaseName(result.rows[0].name, `Postgres ${PostgresUse[use]}`, env)
}
