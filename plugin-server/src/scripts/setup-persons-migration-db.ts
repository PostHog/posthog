import fs from 'fs'
import path from 'path'
import { Client } from 'pg'

function parseDb(urlStr: string): { adminUrl: string; dbName: string } {
    const u = new URL(urlStr)
    const dbName = (u.pathname || '/').replace(/^\//, '') || 'postgres'
    const admin = new URL(u.toString())
    admin.pathname = '/postgres'
    return { adminUrl: admin.toString(), dbName }
}

async function ensureDbExists(adminUrl: string, dbName: string): Promise<void> {
    const admin = new Client({ connectionString: adminUrl })
    await admin.connect()
    try {
        const { rows } = await admin.query('SELECT 1 FROM pg_database WHERE datname = $1', [dbName])
        if (rows.length === 0) {
            await admin.query(`CREATE DATABASE ${JSON.stringify(dbName).replace(/^"|"$/g, '')}`)
        }
    } finally {
        await admin.end()
    }
}

async function dropDbIfExists(adminUrl: string, dbName: string): Promise<void> {
    const admin = new Client({ connectionString: adminUrl })
    await admin.connect()
    try {
        // terminate existing connections to allow DROP
        await admin.query(
            `
      SELECT pg_terminate_backend(pid)
      FROM pg_stat_activity
      WHERE datname = $1 AND pid <> pg_backend_pid()
    `,
            [dbName]
        )
        await admin.query(`DROP DATABASE IF EXISTS ${JSON.stringify(dbName).replace(/^"|"$/g, '')}`)
    } finally {
        await admin.end()
    }
}

async function applySchema(dbUrl: string, sqlFile: string): Promise<void> {
    const sql = fs.readFileSync(sqlFile, 'utf8')
    const client = new Client({ connectionString: dbUrl })
    await client.connect()
    try {
        await client.query(sql)
    } finally {
        await client.end()
    }
}

async function checkPreparedTransactions(dbUrl: string): Promise<void> {
    const client = new Client({ connectionString: dbUrl })
    await client.connect()
    try {
        const { rows } = await client.query(`SHOW max_prepared_transactions`)
        const val = parseInt(rows[0].max_prepared_transactions, 10)
        if (!Number.isFinite(val) || val <= 0) {
            console.warn(
                'Warning: max_prepared_transactions is 0; two-phase commit will not work. Set it > 0 for full dual-write tests.'
            )
        }
    } catch {
        // ignore
    } finally {
        await client.end()
    }
}

async function main() {
    const defaultUrl = 'postgres://posthog:posthog@localhost:5432/test_posthog_persons_migration'
    const dbUrl = process.env.PERSONS_MIGRATION_DATABASE_URL || defaultUrl

    const { adminUrl, dbName } = parseDb(dbUrl)
    const sqlPath = path.resolve(__dirname, '../../sql/create_persons_tables.sql')

    // Always drop and recreate for idempotency
    console.log(`Setting up persons migration database: ${dbName}`)

    // Drop existing database if it exists
    await dropDbIfExists(adminUrl, dbName)

    // Create fresh database
    await ensureDbExists(adminUrl, dbName)

    // Apply schema
    await applySchema(dbUrl, sqlPath)

    // Check configuration
    await checkPreparedTransactions(dbUrl)

    console.log(`Database ${dbName} setup completed successfully`)
}

main().catch((err) => {
    console.error(err)
    process.exit(1)
})
