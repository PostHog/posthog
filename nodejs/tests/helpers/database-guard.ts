import { PostgresRouter, PostgresUse } from '~/common/utils/db/postgres'

// Matches "test" only as an underscore- or boundary-delimited token, so real
// test databases (test_posthog, posthog_test) pass while names that merely
// embed the substring (latest, posthog_latest) are still refused.
const TEST_DATABASE_NAME_PATTERN = /(^|_)test(_|$)/i

/**
 * Throws unless `databaseName` looks like a test database — i.e. it contains
 * "test" as an underscore- or boundary-delimited token (test_posthog,
 * posthog_test). Names that merely embed the substring (latest, mytest) are
 * refused.
 *
 * Destructive test helpers (mass DELETE/TRUNCATE) call this before touching a
 * database, so a misconfigured environment (e.g. NODE_ENV/DEBUG or a
 * DATABASE_URL pointing at the dev `posthog` database leaking in from a shell
 * or IDE) produces a loud error instead of silently wiping real dev data.
 */
export function assertTestDatabaseName(databaseName: string, source: string): void {
    if (TEST_DATABASE_NAME_PATTERN.test(databaseName)) {
        return
    }
    throw new Error(
        `🛑 Refusing to run a destructive test helper against database "${databaseName}" (${source}).\n\n` +
            `The database name does not contain "test" as a standalone segment, so it looks\n` +
            `like a real development or production database. Continuing would have deleted\n` +
            `data from it.\n\n` +
            `The nodejs tests expect dedicated test databases (test_posthog, test_persons,\n` +
            `test_behavioral_cohorts on Postgres; posthog_test on ClickHouse). This error\n` +
            `usually means DATABASE_URL, PERSONS_DATABASE_URL, CLICKHOUSE_DATABASE or similar\n` +
            `leaked in from your shell or IDE. Unset them, or create the test databases with\n` +
            `\`pnpm --filter=@posthog/nodejs setup:test\`.`
    )
}

/**
 * Asserts that the database a router's pool actually connects to for the given
 * use is a test database. Queries `current_database()` so the check reflects
 * ground truth regardless of how the connection URL was assembled.
 */
export async function assertRouterTargetsTestDatabase(router: PostgresRouter, use: PostgresUse): Promise<void> {
    const result = await router.query<{ name: string }>(
        use,
        'SELECT current_database() AS name',
        undefined,
        'database-guard'
    )
    assertTestDatabaseName(result.rows[0].name, `Postgres ${PostgresUse[use]}`)
}
