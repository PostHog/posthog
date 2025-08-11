#!/usr/bin/env node

const { execSync } = require('child_process')

function getCountersDbUrl() {
    // Use environment variable if provided (for production/secrets)
    if (process.env.COUNTERS_DATABASE_URL) {
        return process.env.COUNTERS_DATABASE_URL
    }

    // Simple fallback for local development
    const isTest = process.env.NODE_ENV === 'test' || process.env.TEST === '1'
    const dbName = isTest ? 'test_counters' : 'counters'
    return `postgres://posthog:posthog@localhost:5432/${dbName}`
}

function getDbName() {
    return process.env.NODE_ENV === 'test' || process.env.TEST === '1' ? 'test_counters' : 'counters'
}

function createDatabase(dbName, countersDbUrl) {
    try {
        // Parse database URL to extract credentials
        const url = new URL(countersDbUrl)
        const user = url.username || 'postgres'
        const password = url.password || ''
        const host = url.hostname || 'localhost'
        const port = url.port || '5432'

        const env = password ? `PGPASSWORD=${password}` : ''
        const cmd = `${env} psql -h ${host} -p ${port} -U ${user} -d postgres -c "CREATE DATABASE ${dbName}"`

        execSync(cmd, { stdio: 'ignore' })
    } catch (error) {
        // Database might already exist, which is fine
    }
}

function runMigrations(countersDbUrl) {
    execSync(`npx node-pg-migrate up --migrations-dir src/migrations`, {
        env: { ...process.env, DATABASE_URL: countersDbUrl },
        stdio: 'inherit',
    })
}

function main() {
    const countersDbUrl = getCountersDbUrl()

    if (!countersDbUrl) {
        console.error('COUNTERS_DATABASE_URL is not configured')
        process.exit(1)
    }

    console.log('Performing counters migrations')

    const dbName = getDbName()
    console.log('Database name:', dbName)

    createDatabase(dbName, countersDbUrl)

    try {
        runMigrations(countersDbUrl)
        console.log('Counters migrations completed successfully')
    } catch (error) {
        console.error('Migration failed:', error.message)
        process.exit(1)
    }
}

main()
