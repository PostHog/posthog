import { parseArgs } from 'util'

import type { CdpConfig } from '~/cdp/config'
import { CommonConfig, getDefaultCommonConfig } from '~/common/config'
import { buildBehavioralCohortsDatabaseUrl, buildPosthogDatabaseUrl } from '~/common/config/database-url'

import {
    MigrationStore,
    SqlxMigrationStore,
    SqlxShadowResult,
    checkSqlxShadow,
    describeError,
    describeMissing,
    waitForRequirements,
} from './check'
import {
    DEFAULT_MANIFEST_PATH,
    SqlxDatabase,
    SqlxRequirement,
    djangoRequirements,
    readManifest,
    sqlxRequirements,
} from './manifest'
import { FetchFunction, pushMetrics, renderMetrics } from './metrics-push'
import { PostgresMigrationStore, PostgresSqlxMigrationStore } from './postgres-migration-store'

export const EXIT_SATISFIED = 0
export const EXIT_MISSING = 1
export const EXIT_ERROR = 2

const USAGE = `Usage: node nodejs/dist/schema-check/cli.js [--manifest PATH] [--wait-seconds N]

Checks that the main Postgres database has every Django migration this Node build needs.
Exit codes: 0 all applied, 1 migrations missing, 2 the check could not run.
sqlx requirements run in shadow mode: the result is logged and never changes the exit code.

Options:
  --manifest PATH                  Requirements file (default: ${DEFAULT_MANIFEST_PATH})
  --wait-seconds N                 Poll until applied or N seconds pass (default: 0, check once)
  --poll-interval-seconds N        Time between polls (default: 15)
  --connect-timeout-seconds N      Postgres connect timeout (default: 5)
  --statement-timeout-seconds N    Postgres statement timeout (default: 10)

Reads DATABASE_URL, or POSTHOG_DB_NAME, POSTHOG_DB_USER, POSTHOG_DB_PASSWORD,
POSTHOG_POSTGRES_HOST and POSTHOG_POSTGRES_PORT, the same as the Node services.
sqlx databases use PERSONS_DATABASE_URL (or PERSONS_READONLY_DATABASE_URL),
CYCLOTRON_NODE_DATABASE_URL and BEHAVIORAL_COHORTS_DATABASE_URL (or
POSTGRES_BEHAVIORAL_COHORTS_HOST, _USER and _PASSWORD).
The result is pushed to SCHEMA_CHECK_PUSHGATEWAY_URL under SCHEMA_CHECK_APP when both are set.`

export interface CliDependencies {
    createStore: (databaseUrl: string, connectTimeoutMs: number, statementTimeoutMs: number) => MigrationStore
    createSqlxStore: (databaseUrl: string, connectTimeoutMs: number, statementTimeoutMs: number) => SqlxMigrationStore
    sleep?: (ms: number) => Promise<void>
    fetch: FetchFunction
    log: (message: string) => void
    logError: (message: string) => void
}

const defaultDependencies: CliDependencies = {
    createStore: (databaseUrl, connectTimeoutMs, statementTimeoutMs) =>
        new PostgresMigrationStore({ databaseUrl, connectTimeoutMs, statementTimeoutMs }),
    createSqlxStore: (databaseUrl, connectTimeoutMs, statementTimeoutMs) =>
        new PostgresSqlxMigrationStore({ databaseUrl, connectTimeoutMs, statementTimeoutMs }),
    // A one-shot Job, so it skips the request util's pooled agents and metrics that long-running services need.
    // eslint-disable-next-line no-restricted-globals
    fetch: (url, init) => fetch(url, init),
    log: (message) => console.log(message),
    logError: (message) => console.error(message),
}

// Uses the primary through DATABASE_URL. DATABASE_READONLY_URL is never read because replica lag hides fresh migrations.
export function resolveDatabaseUrl(env: Record<string, string | undefined>): string {
    const defaults = getDefaultCommonConfig()
    return buildPosthogDatabaseUrl({
        DATABASE_URL: env.DATABASE_URL ?? defaults.DATABASE_URL,
        POSTHOG_DB_NAME: env.POSTHOG_DB_NAME ?? defaults.POSTHOG_DB_NAME,
        POSTHOG_DB_USER: env.POSTHOG_DB_USER ?? defaults.POSTHOG_DB_USER,
        POSTHOG_DB_PASSWORD: env.POSTHOG_DB_PASSWORD ?? defaults.POSTHOG_DB_PASSWORD,
        POSTHOG_POSTGRES_HOST: env.POSTHOG_POSTGRES_HOST ?? defaults.POSTHOG_POSTGRES_HOST,
        POSTHOG_POSTGRES_PORT: env.POSTHOG_POSTGRES_PORT
            ? parseInt(env.POSTHOG_POSTGRES_PORT, 10)
            : defaults.POSTHOG_POSTGRES_PORT,
    })
}

// The keys must stay names of the Node config, so a rename there fails to compile here instead of turning into a skip.
const PERSONS_URL_KEYS = [
    'PERSONS_DATABASE_URL',
    'PERSONS_READONLY_DATABASE_URL',
] as const satisfies readonly (keyof CommonConfig)[]
const CYCLOTRON_NODE_URL_KEY = 'CYCLOTRON_NODE_DATABASE_URL' satisfies keyof CdpConfig
const PUSHGATEWAY_URL_KEY = 'SCHEMA_CHECK_PUSHGATEWAY_URL' satisfies keyof CommonConfig
const PUSH_APP_KEY = 'SCHEMA_CHECK_APP' satisfies keyof CommonConfig

// Reads the same variables as the Node services, without the dev defaults, so an empty result means the app does not use the database.
export function resolveSqlxDatabaseUrl(database: SqlxDatabase, env: Record<string, string | undefined>): string {
    if (database === 'persons') {
        // Most ingestion apps get only the read-only persons URL. Replica lag can only make the check wait longer.
        const key = PERSONS_URL_KEYS.find((name) => env[name])
        return key ? env[key]! : ''
    }
    if (database === 'cyclotron-node') {
        return env[CYCLOTRON_NODE_URL_KEY] || ''
    }
    return buildBehavioralCohortsDatabaseUrl({
        BEHAVIORAL_COHORTS_DATABASE_URL: env.BEHAVIORAL_COHORTS_DATABASE_URL ?? '',
        POSTGRES_BEHAVIORAL_COHORTS_HOST: env.POSTGRES_BEHAVIORAL_COHORTS_HOST ?? '',
        POSTGRES_BEHAVIORAL_COHORTS_USER: env.POSTGRES_BEHAVIORAL_COHORTS_USER ?? '',
        POSTGRES_BEHAVIORAL_COHORTS_PASSWORD: env.POSTGRES_BEHAVIORAL_COHORTS_PASSWORD ?? '',
    })
}

async function logSqlxShadow(
    requirements: SqlxRequirement[],
    env: Record<string, string | undefined>,
    options: { connectTimeoutMs: number; statementTimeoutMs: number },
    deps: CliDependencies
): Promise<SqlxShadowResult[]> {
    const results = await Promise.all(
        requirements.map((requirement) => {
            const databaseUrl = resolveSqlxDatabaseUrl(requirement.database, env)
            const store = databaseUrl
                ? deps.createSqlxStore(databaseUrl, options.connectTimeoutMs, options.statementTimeoutMs)
                : null
            return checkSqlxShadow(requirement, store)
        })
    )
    for (const result of results) {
        deps.log(
            `Shadow sqlx check (does not block): ${result.requirement.database} ${result.status}, ${result.detail}`
        )
    }
    return results
}

function parseSeconds(name: string, value: string | undefined, fallback: number): number {
    if (value === undefined) {
        return fallback
    }
    const seconds = Number(value)
    if (!Number.isFinite(seconds) || seconds < 0) {
        throw new Error(`--${name} must be a number of seconds, got "${value}"`)
    }
    return seconds
}

// Earlier exits push nothing, because the alerts only read runs that reached the database.
async function pushResult(
    djangoExitCode: number,
    sqlx: SqlxShadowResult[],
    env: Record<string, string | undefined>,
    deps: CliDependencies
): Promise<number> {
    const pushgatewayUrl = env[PUSHGATEWAY_URL_KEY]
    const app = env[PUSH_APP_KEY]
    if (!pushgatewayUrl || !app) {
        deps.log('Schema check metrics push skipped, SCHEMA_CHECK_PUSHGATEWAY_URL or SCHEMA_CHECK_APP is not set')
        return djangoExitCode
    }
    const body = renderMetrics(djangoExitCode, sqlx, Math.floor(Date.now() / 1000))
    await pushMetrics(body, { pushgatewayUrl, app }, deps.fetch, deps.logError)
    return djangoExitCode
}

export async function runCli(
    argv: string[],
    env: Record<string, string | undefined>,
    deps: CliDependencies = defaultDependencies
): Promise<number> {
    let options: {
        manifestPath: string
        waitSeconds: number
        pollIntervalSeconds: number
        connectTimeoutSeconds: number
        statementTimeoutSeconds: number
    }
    try {
        const { values } = parseArgs({
            args: argv,
            options: {
                manifest: { type: 'string' },
                'wait-seconds': { type: 'string' },
                'poll-interval-seconds': { type: 'string' },
                'connect-timeout-seconds': { type: 'string' },
                'statement-timeout-seconds': { type: 'string' },
                help: { type: 'boolean' },
            },
        })
        if (values.help) {
            deps.log(USAGE)
            return EXIT_SATISFIED
        }
        options = {
            manifestPath: values.manifest ?? DEFAULT_MANIFEST_PATH,
            waitSeconds: parseSeconds('wait-seconds', values['wait-seconds'], 0),
            pollIntervalSeconds: parseSeconds('poll-interval-seconds', values['poll-interval-seconds'], 15),
            connectTimeoutSeconds: parseSeconds('connect-timeout-seconds', values['connect-timeout-seconds'], 5),
            statementTimeoutSeconds: parseSeconds('statement-timeout-seconds', values['statement-timeout-seconds'], 10),
        }
    } catch (error) {
        deps.logError(`Schema check error: ${error.message}\n\n${USAGE}`)
        return EXIT_ERROR
    }

    let store: MigrationStore
    let manifest: ReturnType<typeof readManifest>
    try {
        manifest = readManifest(options.manifestPath)
        store = deps.createStore(
            resolveDatabaseUrl(env),
            options.connectTimeoutSeconds * 1000,
            options.statementTimeoutSeconds * 1000
        )
    } catch (error) {
        deps.logError(`Schema check error: ${error.message}`)
        return EXIT_ERROR
    }

    const django = djangoRequirements(manifest)
    const sqlx = sqlxRequirements(manifest)
    deps.log(
        `Checking ${django.length} Django apps and ${sqlx.length} sqlx databases in shadow mode (manifest ${manifest.digest}, commit ${manifest.source_commit ?? 'unknown'})`
    )
    const outcome = await waitForRequirements(django, store, {
        waitSeconds: options.waitSeconds,
        pollIntervalMs: options.pollIntervalSeconds * 1000,
        sleep: deps.sleep,
        log: deps.log,
    })
    // Runs after the Django wait so that the log shows the sqlx state at the moment the Deployment would roll.
    const sqlxResults = await logSqlxShadow(
        sqlx,
        env,
        {
            connectTimeoutMs: options.connectTimeoutSeconds * 1000,
            statementTimeoutMs: options.statementTimeoutSeconds * 1000,
        },
        deps
    )

    if (outcome.status === 'satisfied') {
        deps.log('All required Django migrations are applied.')
        return pushResult(EXIT_SATISFIED, sqlxResults, env, deps)
    }
    if (outcome.status === 'error') {
        deps.logError(`Schema check error: could not read django_migrations: ${describeError(outcome.error)}`)
        return pushResult(EXIT_ERROR, sqlxResults, env, deps)
    }
    deps.logError('Required Django migrations are not applied yet:')
    describeMissing(outcome.missing, outcome.latestApplied).forEach((line) => deps.logError(`  ${line}`))
    return pushResult(EXIT_MISSING, sqlxResults, env, deps)
}

if (require.main === module) {
    void runCli(process.argv.slice(2), process.env).then((code) => {
        process.exitCode = code
    })
}
