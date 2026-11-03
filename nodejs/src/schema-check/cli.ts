import { parseArgs } from 'util'

import { getDefaultCommonConfig } from '~/common/config'
import { buildPosthogDatabaseUrl } from '~/common/config/database-url'

import { MigrationStore, describeError, describeMissing, waitForRequirements } from './check'
import { DEFAULT_MANIFEST_PATH, readManifest } from './manifest'
import { PostgresMigrationStore } from './postgres-migration-store'

export const EXIT_SATISFIED = 0
export const EXIT_MISSING = 1
export const EXIT_ERROR = 2

const USAGE = `Usage: node nodejs/dist/schema-check/cli.js [--manifest PATH] [--wait-seconds N]

Checks that the main Postgres database has every Django migration this Node build needs.
Exit codes: 0 all applied, 1 migrations missing, 2 the check could not run.

Options:
  --manifest PATH                  Requirements file (default: ${DEFAULT_MANIFEST_PATH})
  --wait-seconds N                 Poll until applied or N seconds pass (default: 0, check once)
  --poll-interval-seconds N        Time between polls (default: 15)
  --connect-timeout-seconds N      Postgres connect timeout (default: 5)
  --statement-timeout-seconds N    Postgres statement timeout (default: 10)

Reads DATABASE_URL, or POSTHOG_DB_NAME, POSTHOG_DB_USER, POSTHOG_DB_PASSWORD,
POSTHOG_POSTGRES_HOST and POSTHOG_POSTGRES_PORT, the same as the Node services.`

export interface CliDependencies {
    createStore: (databaseUrl: string, connectTimeoutMs: number, statementTimeoutMs: number) => MigrationStore
    sleep?: (ms: number) => Promise<void>
    log: (message: string) => void
    logError: (message: string) => void
}

const defaultDependencies: CliDependencies = {
    createStore: (databaseUrl, connectTimeoutMs, statementTimeoutMs) =>
        new PostgresMigrationStore({ databaseUrl, connectTimeoutMs, statementTimeoutMs }),
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

    deps.log(
        `Checking ${manifest.requirements.length} Django apps (manifest ${manifest.digest}, commit ${manifest.source_commit ?? 'unknown'})`
    )
    const outcome = await waitForRequirements(manifest.requirements, store, {
        waitSeconds: options.waitSeconds,
        pollIntervalMs: options.pollIntervalSeconds * 1000,
        sleep: deps.sleep,
        log: deps.log,
    })

    if (outcome.status === 'satisfied') {
        deps.log('All required Django migrations are applied.')
        return EXIT_SATISFIED
    }
    if (outcome.status === 'error') {
        deps.logError(`Schema check error: could not read django_migrations: ${describeError(outcome.error)}`)
        return EXIT_ERROR
    }
    deps.logError('Required Django migrations are not applied yet:')
    describeMissing(outcome.missing, outcome.latestApplied).forEach((line) => deps.logError(`  ${line}`))
    return EXIT_MISSING
}

if (require.main === module) {
    void runCli(process.argv.slice(2), process.env).then((code) => {
        process.exitCode = code
    })
}
