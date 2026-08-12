import { createHash } from 'node:crypto'
import { readdir, readFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import pg from 'pg'

import type { ServiceLogger } from '@posthog/node-service'

const { Client } = pg

interface Migration {
    checksum: string
    name: string
    upSql: string
}

interface AppliedMigration {
    checksum: string
    name: string
}

interface MigrationLogger {
    debug(message: string): void
    info(message: string): void
    warn(message: string): void
    error(message: string): void
}

export interface RunPostgresMigrationsOptions {
    databaseUrl: string
    serviceName: string
    migrationsDirectory?: string
    logger?: ServiceLogger
    advisoryLockMode?: 'fail' | 'wait'
}

const silentLogger: MigrationLogger = {
    debug: () => undefined,
    info: () => undefined,
    warn: () => undefined,
    error: () => undefined,
}

function loggerFor(serviceLogger: ServiceLogger | undefined): MigrationLogger {
    if (!serviceLogger) {
        return silentLogger
    }
    return {
        debug: (message) => serviceLogger.debug({ event: 'database.migration' }, message),
        info: (message) => serviceLogger.info({ event: 'database.migration' }, message),
        warn: (message) => serviceLogger.warn({ event: 'database.migration' }, message),
        error: (message) => serviceLogger.error({ event: 'database.migration' }, message),
    }
}

export function migrationTableForService(serviceName: string): string {
    if (!/^[a-z](?:[a-z0-9-]*[a-z0-9])?$/.test(serviceName)) {
        throw new Error('Service name must use lowercase letters, numbers, and hyphens')
    }
    return `${serviceName.replaceAll('-', '_')}_schema_migrations`
}

async function loadMigrations(directory: string): Promise<Migration[]> {
    const filenames = (await readdir(directory))
        .filter((filename) => filename.endsWith('.sql'))
        .toSorted((left, right) => left.localeCompare(right))
    const migrations: Migration[] = []

    for (const filename of filenames) {
        if (!/^\d{4}_[a-z0-9_]+\.sql$/.test(filename)) {
            throw new Error(`Invalid migration filename: ${filename}`)
        }
        const sql = await readFile(resolve(directory, filename), 'utf8')
        const upMarker = sql.indexOf('-- Up Migration')
        if (upMarker === -1) {
            throw new Error(`Migration ${filename} is missing the Up Migration marker`)
        }
        const downMarker = sql.indexOf('-- Down Migration', upMarker)
        const upSql = sql.slice(upMarker + '-- Up Migration'.length, downMarker === -1 ? undefined : downMarker).trim()
        if (!upSql) {
            throw new Error(`Migration ${filename} has no up SQL`)
        }
        migrations.push({
            name: filename.slice(0, -'.sql'.length),
            checksum: createHash('sha256').update(upSql).digest('hex'),
            upSql,
        })
    }

    return migrations
}

export async function runPostgresMigrations(options: RunPostgresMigrationsOptions): Promise<void> {
    const migrations = await loadMigrations(options.migrationsDirectory ?? resolve(process.cwd(), 'migrations'))
    const migrationTable = migrationTableForService(options.serviceName)
    const logger = loggerFor(options.logger)
    const client = new Client({ connectionString: options.databaseUrl })
    let inTransaction = false
    let lockAcquired = false

    // migrationTable is derived from the strictly validated service name, so it is safe to use as a SQL identifier.
    const quotedMigrationTable = `"${migrationTable}"`

    try {
        await client.connect()
        if (options.advisoryLockMode === 'wait') {
            await client.query('SELECT pg_advisory_lock(hashtext($1), hashtext($2))', [
                'posthog-node-migrations',
                options.serviceName,
            ])
            lockAcquired = true
        } else {
            const lockResult = await client.query<{ acquired: boolean }>(
                'SELECT pg_try_advisory_lock(hashtext($1), hashtext($2)) AS acquired',
                ['posthog-node-migrations', options.serviceName]
            )
            lockAcquired = lockResult.rows[0]?.acquired === true
            if (!lockAcquired) {
                throw new Error(`Another ${options.serviceName} migration is already running`)
            }
        }

        await client.query('BEGIN')
        inTransaction = true
        await client.query(`
            CREATE TABLE IF NOT EXISTS ${quotedMigrationTable} (
                name text PRIMARY KEY,
                checksum text NOT NULL,
                applied_at timestamptz NOT NULL DEFAULT now()
            )
        `)

        const appliedResult = await client.query<AppliedMigration>(
            `SELECT name, checksum FROM ${quotedMigrationTable} ORDER BY name`
        )
        const availableByName = new Map(migrations.map((migration) => [migration.name, migration]))

        for (const [index, applied] of appliedResult.rows.entries()) {
            if (migrations[index]?.name !== applied.name) {
                throw new Error(`Migration ${migrations[index]?.name ?? 'unknown'} sorts before an applied migration`)
            }
            const available = availableByName.get(applied.name)
            if (!available) {
                throw new Error(`Applied migration ${applied.name} is missing from the service`)
            }
            if (available.checksum !== applied.checksum) {
                throw new Error(`Applied migration ${applied.name} has changed`)
            }
        }

        const appliedNames = new Set(appliedResult.rows.map((migration) => migration.name))
        const pending = migrations.filter((migration) => !appliedNames.has(migration.name))
        if (pending.length === 0) {
            logger.info('No migrations to run')
        }

        for (const migration of pending) {
            logger.info(`Applying ${migration.name}`)
            await client.query(migration.upSql)
            await client.query(`INSERT INTO ${quotedMigrationTable} (name, checksum) VALUES ($1, $2)`, [
                migration.name,
                migration.checksum,
            ])
        }

        await client.query('COMMIT')
        inTransaction = false
    } catch (error) {
        if (inTransaction) {
            await client.query('ROLLBACK')
        }
        logger.error(error instanceof Error ? error.message : String(error))
        throw error
    } finally {
        if (lockAcquired) {
            await client.query('SELECT pg_advisory_unlock(hashtext($1), hashtext($2))', [
                'posthog-node-migrations',
                options.serviceName,
            ])
        }
        await client.end()
    }
}
