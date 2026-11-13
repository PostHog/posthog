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

export interface SqlxMigrationRow {
    version: number
    success: boolean
}

export interface SqlxMigrationStore {
    // Returns the rows for the given versions plus every row with success = false.
    fetchRows(versions: number[]): Promise<SqlxMigrationRow[]>
}

export type SqlxStatus = 'satisfied' | 'missing' | 'dirty' | 'skipped' | 'error'

export interface SqlxResult {
    requirement: SqlxRequirement
    status: SqlxStatus
    detail: string
}

export interface SqlxCheck {
    requirement: SqlxRequirement
    store: SqlxMigrationStore | null
}

// sqlx writes success = false when a migration without a transaction fails halfway. sqlx refuses to run on such a database.
export function evaluateSqlxRows(requirement: SqlxRequirement, rows: SqlxMigrationRow[]): SqlxResult {
    const failed = rows.filter((row) => !row.success).map((row) => row.version)
    if (failed.length > 0) {
        return {
            requirement,
            status: 'dirty',
            detail: `failed migrations recorded: ${failed.join(', ')}, sqlx-migrate stops until someone repairs them`,
        }
    }
    const applied = new Set(rows.map((row) => row.version))
    const missing = requirement.versions.filter((version) => !applied.has(version))
    if (missing.length === 0) {
        const latest = requirement.versions[requirement.versions.length - 1]
        return {
            requirement,
            status: 'satisfied',
            detail: `all ${requirement.versions.length} versions are applied, latest ${latest}`,
        }
    }
    return { requirement, status: 'missing', detail: `versions not applied: ${missing.join(', ')}` }
}

export async function checkSqlxOnce({ requirement, store }: SqlxCheck): Promise<SqlxResult> {
    // Node has no production default for these URLs, so an app without one does not use that database.
    if (store === null) {
        return { requirement, status: 'skipped', detail: 'no database URL in this environment' }
    }
    try {
        return evaluateSqlxRows(requirement, await store.fetchRows(requirement.versions))
    } catch (error) {
        return {
            requirement,
            status: 'error',
            detail: describeError(error instanceof Error ? error : new Error(String(error))),
        }
    }
}

// A skipped database counts as satisfied, because an app without a URL for it never connects to it
// and so cannot read a table that a missing version creates.
export function isSqlxSatisfied(result: SqlxResult): boolean {
    return result.status === 'satisfied' || result.status === 'skipped'
}

export interface WaitResult {
    django: CheckOutcome
    sqlx: SqlxResult[]
}

function isWaitSatisfied(result: WaitResult): boolean {
    return result.django.status === 'satisfied' && result.sqlx.every(isSqlxSatisfied)
}

async function checkAllOnce(
    djangoRequirements: DjangoRequirement[],
    store: MigrationStore,
    sqlxChecks: SqlxCheck[]
): Promise<WaitResult> {
    const [django, sqlx] = await Promise.all([
        checkOnce(djangoRequirements, store),
        Promise.all(sqlxChecks.map(checkSqlxOnce)),
    ])
    return { django, sqlx }
}

function logWaiting(result: WaitResult, log: (message: string) => void): void {
    if (result.django.status === 'missing') {
        const names = result.django.missing.map((item) => `${item.app}.${item.migration}`)
        log(`Waiting for ${names.length} migrations: ${names.join(', ')}`)
    } else if (result.django.status === 'error') {
        log(`Waiting: could not read django_migrations: ${describeError(result.django.error)}`)
    }
    for (const sqlx of result.sqlx.filter((item) => !isSqlxSatisfied(item))) {
        log(`Waiting for sqlx database ${sqlx.requirement.database}: ${sqlx.status}, ${sqlx.detail}`)
    }
}

// Database errors count as "not yet" while time remains, because the hook can start before a failover settles.
// A dirty sqlx database also waits, the same as a Django migration that failed and so is still missing.
export async function waitForRequirements(
    djangoRequirements: DjangoRequirement[],
    store: MigrationStore,
    sqlxChecks: SqlxCheck[],
    options: WaitOptions
): Promise<WaitResult> {
    const now = options.now ?? Date.now
    const sleep = options.sleep ?? defaultSleep
    const log = options.log ?? ((): void => {})
    const deadline = now() + options.waitSeconds * 1000

    for (;;) {
        const result = await checkAllOnce(djangoRequirements, store, sqlxChecks)
        if (isWaitSatisfied(result)) {
            return result
        }

        const remainingMs = deadline - now()
        if (remainingMs <= 0) {
            return result
        }

        logWaiting(result, log)
        await sleep(Math.min(options.pollIntervalMs, remainingMs))
    }
}
