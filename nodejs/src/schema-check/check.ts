import { DjangoRequirement, SqlxRequirement } from './manifest'

export interface AppliedMigration {
    app: string
    name: string
}

export interface MigrationStore {
    fetchApplied(keys: AppliedMigration[]): Promise<AppliedMigration[]>
    fetchLatestApplied(apps: string[]): Promise<Map<string, string>>
}

export type CheckOutcome =
    | { status: 'satisfied' }
    | { status: 'missing'; missing: DjangoRequirement[]; latestApplied: Map<string, string> }
    | { status: 'error'; error: Error }

export interface WaitOptions {
    waitSeconds: number
    pollIntervalMs: number
    now?: () => number
    sleep?: (ms: number) => Promise<void>
    log?: (message: string) => void
}

function migrationKey(app: string, name: string): string {
    return `${app}.${name}`
}

export function requiredMigrationKeys(requirements: DjangoRequirement[]): AppliedMigration[] {
    return requirements.flatMap((requirement) => [
        { app: requirement.app, name: requirement.migration },
        ...(requirement.replaces ?? []).map((name) => ({ app: requirement.app, name })),
    ])
}

// Django records a squash as applied once all migrations it replaces are applied, even without its own row.
export function findMissingRequirements(
    requirements: DjangoRequirement[],
    applied: AppliedMigration[]
): DjangoRequirement[] {
    const appliedKeys = new Set(applied.map((row) => migrationKey(row.app, row.name)))
    return requirements.filter((requirement) => {
        if (appliedKeys.has(migrationKey(requirement.app, requirement.migration))) {
            return false
        }
        const replaces = requirement.replaces ?? []
        const replacedAllApplied =
            replaces.length > 0 && replaces.every((name) => appliedKeys.has(migrationKey(requirement.app, name)))
        return !replacedAllApplied
    })
}

export function describeMissing(missing: DjangoRequirement[], latestApplied: Map<string, string>): string[] {
    return missing.map((requirement) => {
        const latest = latestApplied.get(requirement.app)
        const has = latest ? `has up to ${latest}` : 'has no migrations for this app'
        return `needs ${requirement.app}.${requirement.migration}, ${has}`
    })
}

// Node reports a refused connection to every resolved address as an AggregateError with an empty message.
export function describeError(error: Error): string {
    return error.message || (error as NodeJS.ErrnoException).code || error.name
}

export async function checkOnce(requirements: DjangoRequirement[], store: MigrationStore): Promise<CheckOutcome> {
    try {
        const applied = await store.fetchApplied(requiredMigrationKeys(requirements))
        const missing = findMissingRequirements(requirements, applied)
        if (missing.length === 0) {
            return { status: 'satisfied' }
        }
        const latestApplied = await store.fetchLatestApplied([...new Set(missing.map((item) => item.app))])
        return { status: 'missing', missing, latestApplied }
    } catch (error) {
        return { status: 'error', error: error instanceof Error ? error : new Error(String(error)) }
    }
}

function defaultSleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms))
}

// Database errors count as "not yet" while time remains, because the hook can start before a failover settles.
export async function waitForRequirements(
    requirements: DjangoRequirement[],
    store: MigrationStore,
    options: WaitOptions
): Promise<CheckOutcome> {
    const now = options.now ?? Date.now
    const sleep = options.sleep ?? defaultSleep
    const log = options.log ?? ((): void => {})
    const deadline = now() + options.waitSeconds * 1000

    for (;;) {
        const outcome = await checkOnce(requirements, store)
        if (outcome.status === 'satisfied') {
            return outcome
        }

        const remainingMs = deadline - now()
        if (remainingMs <= 0) {
            return outcome
        }

        if (outcome.status === 'missing') {
            const names = outcome.missing.map((item) => `${item.app}.${item.migration}`)
            log(`Waiting for ${names.length} migrations: ${names.join(', ')}`)
        } else {
            log(`Waiting: could not read django_migrations: ${describeError(outcome.error)}`)
        }
        await sleep(Math.min(options.pollIntervalMs, remainingMs))
    }
}

export interface SqlxMigrationRow {
    version: number
    success: boolean
}

export interface SqlxMigrationStore {
    // Returns the rows for the given versions plus every row with success = false.
    fetchRows(versions: number[]): Promise<SqlxMigrationRow[]>
}

export type SqlxShadowStatus = 'satisfied' | 'missing' | 'dirty' | 'skipped' | 'error'

export interface SqlxShadowResult {
    requirement: SqlxRequirement
    status: SqlxShadowStatus
    detail: string
}

// sqlx writes success = false when a migration without a transaction fails halfway. sqlx refuses to run on such a database.
export function evaluateSqlxRows(requirement: SqlxRequirement, rows: SqlxMigrationRow[]): SqlxShadowResult {
    const failed = rows.filter((row) => !row.success).map((row) => row.version)
    if (failed.length > 0) {
        return { requirement, status: 'dirty', detail: `failed migrations recorded: ${failed.join(', ')}` }
    }
    if (rows.some((row) => row.version === requirement.version)) {
        return { requirement, status: 'satisfied', detail: `version ${requirement.version} is applied` }
    }
    return { requirement, status: 'missing', detail: `version ${requirement.version} is not applied` }
}

export async function checkSqlxShadow(
    requirement: SqlxRequirement,
    store: SqlxMigrationStore | null
): Promise<SqlxShadowResult> {
    // Node has no production default for these URLs, so an app without one does not use that database.
    if (store === null) {
        return { requirement, status: 'skipped', detail: 'no database URL in this environment' }
    }
    try {
        return evaluateSqlxRows(requirement, await store.fetchRows([requirement.version]))
    } catch (error) {
        return {
            requirement,
            status: 'error',
            detail: describeError(error instanceof Error ? error : new Error(String(error))),
        }
    }
}
