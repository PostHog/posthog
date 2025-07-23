#!/usr/bin/env node

const cassandra = require('cassandra-driver')
const fs = require('fs')
const path = require('path')

// Configuration
const config = {
    contactPoints: [process.env.CASSANDRA_HOST || 'localhost'],
    localDataCenter: 'datacenter1',
    keyspace: process.env.CASSANDRA_KEYSPACE || 'posthog',
}

const client = new cassandra.Client(config)

async function createKeyspace() {
    const systemClient = new cassandra.Client({
        contactPoints: config.contactPoints,
        localDataCenter: 'datacenter1',
    })

    try {
        await systemClient.connect()
        console.log("Creating keyspace if it doesn't exist...")

        await systemClient.execute(`
            CREATE KEYSPACE IF NOT EXISTS ${config.keyspace}
            WITH REPLICATION = {
                'class': 'SimpleStrategy',
                'replication_factor': 1
            }
        `)

        console.log(`Keyspace '${config.keyspace}' is ready`)
    } finally {
        await systemClient.shutdown()
    }
}

async function createMigrationTable() {
    try {
        // Check if table already exists
        const result = await client.execute(
            'SELECT table_name FROM system_schema.tables WHERE keyspace_name = ? AND table_name = ?',
            [config.keyspace, 'migration_history']
        )

        if (result.rows.length > 0) {
            console.log('⏭️  Migration tracking table already exists, skipping creation')
        } else {
            console.log('Creating migration tracking table...')
            await client.execute(`
                CREATE TABLE IF NOT EXISTS migration_history (
                    filename TEXT,
                    executed_at TIMESTAMP,
                    PRIMARY KEY (filename)
                )
            `)
            console.log('✅ Migration tracking table created')
        }
    } catch (error) {
        // Fallback to simple creation if system tables query fails
        console.log('Creating migration tracking table...')
        await client.execute(`
            CREATE TABLE IF NOT EXISTS migration_history (
                filename TEXT,
                executed_at TIMESTAMP,
                PRIMARY KEY (filename)
            )
        `)
    }
}

async function getExecutedMigrations() {
    try {
        const result = await client.execute('SELECT filename FROM migration_history')
        return new Set(result.rows.map((row) => row.filename))
    } catch (error) {
        // Table might not exist yet
        return new Set()
    }
}

async function executeMigration(filename, content) {
    console.log(`Executing migration: ${filename}`)

    // Split content by semicolons to handle multiple statements
    const statements = content
        .split(';')
        .map((stmt) => stmt.trim())
        .filter((stmt) => stmt.length > 0 && !stmt.startsWith('--'))

    for (const statement of statements) {
        if (statement.trim()) {
            await client.execute(statement)
        }
    }

    // Record the migration as executed
    await client.execute('INSERT INTO migration_history (filename, executed_at) VALUES (?, ?)', [filename, new Date()])

    console.log(`✅ Migration ${filename} completed`)
}

async function runMigrations() {
    try {
        // Create keyspace first
        await createKeyspace()

        // Connect to the keyspace
        await client.connect()
        console.log(`Connected to Cassandra keyspace: ${config.keyspace}`)

        // Create migration tracking table
        await createMigrationTable()

        // Get list of executed migrations
        const executedMigrations = await getExecutedMigrations()

        // Read migration files
        const migrationsDir = path.join(__dirname, 'migrations')
        if (!fs.existsSync(migrationsDir)) {
            console.log('No migrations directory found, creating one...')
            fs.mkdirSync(migrationsDir, { recursive: true })
            console.log('✅ All migrations completed (no migration files found)')
            return
        }

        const migrationFiles = fs
            .readdirSync(migrationsDir)
            .filter((file) => file.endsWith('.cql'))
            .sort()

        if (migrationFiles.length === 0) {
            console.log('✅ All migrations completed (no migration files found)')
            return
        }

        // Execute pending migrations
        let executed = 0
        for (const filename of migrationFiles) {
            if (!executedMigrations.has(filename)) {
                const filePath = path.join(migrationsDir, filename)
                const content = fs.readFileSync(filePath, 'utf8')
                await executeMigration(filename, content)
                executed++
            } else {
                console.log(`⏭️  Skipping already executed migration: ${filename}`)
            }
        }

        if (executed === 0) {
            console.log('✅ All migrations are up to date')
        } else {
            console.log(`✅ Executed ${executed} migration(s) successfully`)
        }
    } catch (error) {
        console.error('❌ Migration failed:', error.message)
        process.exit(1)
    } finally {
        await client.shutdown()
    }
}

// Run migrations
await runMigrations()
