import { mkdtemp, rm, unlink, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import pg from 'pg'

import { migrationTableForService, runPostgresMigrations } from '../../src/migrations.js'

const { Pool } = pg
const TEST_DATABASE_URL = 'postgres://posthog:posthog@localhost:5432/test_posthog'

function getTestDatabaseUrl(): string {
    const databaseUrl = process.env.DATABASE_URL ?? TEST_DATABASE_URL
    const databaseName = new URL(databaseUrl).pathname.slice(1)
    if (!databaseName.includes('test')) {
        throw new Error(`Refusing to run migration tests against database ${databaseName}`)
    }
    return databaseUrl
}

describe('Postgres migrations', () => {
    const databaseUrl = getTestDatabaseUrl()
    const serviceName = `migration-test-${process.pid}`
    const dataTable = `migration_test_data_${process.pid}`
    const historyTable = migrationTableForService(serviceName)
    const pool = new Pool({ connectionString: databaseUrl })
    let migrationsDirectory: string
    let migrationFile: string

    beforeAll(async () => {
        migrationsDirectory = await mkdtemp(join(tmpdir(), 'posthog-node-migrations-'))
        migrationFile = join(migrationsDirectory, '0001_create_data.sql')
    })

    afterAll(async () => {
        await pool.query(`DROP TABLE IF EXISTS "${dataTable}"`)
        await pool.query(`DROP TABLE IF EXISTS "${historyTable}"`)
        await pool.end()
        await rm(migrationsDirectory, { recursive: true, force: true })
    })

    it('records applied migrations and rejects edits to their SQL', async () => {
        const initialSql = `-- Up Migration\nCREATE TABLE "${dataTable}" (id integer PRIMARY KEY);\n-- Down Migration\nDROP TABLE "${dataTable}";\n`
        await writeFile(migrationFile, initialSql)

        await runPostgresMigrations({ databaseUrl, serviceName, migrationsDirectory })
        await runPostgresMigrations({ databaseUrl, serviceName, migrationsDirectory })

        const history = await pool.query<{ name: string }>(`SELECT name FROM "${historyTable}"`)
        expect(history.rows).toEqual([{ name: '0001_create_data' }])

        const earlierMigration = join(migrationsDirectory, '0000_added_late.sql')
        await writeFile(earlierMigration, '-- Up Migration\nSELECT 1;\n')
        await expect(runPostgresMigrations({ databaseUrl, serviceName, migrationsDirectory })).rejects.toThrow(
            'Migration 0000_added_late sorts before an applied migration'
        )
        await unlink(earlierMigration)

        await writeFile(migrationFile, initialSql.replace('PRIMARY KEY', 'PRIMARY KEY CHECK (id > 0)'))
        await expect(runPostgresMigrations({ databaseUrl, serviceName, migrationsDirectory })).rejects.toThrow(
            'Applied migration 0001_create_data has changed'
        )
    })
})
