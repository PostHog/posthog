#!/usr/bin/env node

const { Client } = require('pg')
const fs = require('fs')
const path = require('path')

async function fetchPostHogKey() {
    const envPath = path.join(__dirname, '..', '.env.local')

    // Check if .env.local already exists with a valid key
    if (fs.existsSync(envPath) && !process.env.FORCE_FETCH_KEY) {
        const envContent = fs.readFileSync(envPath, 'utf-8')
        const keyMatch = envContent.match(/NEXT_PUBLIC_POSTHOG_KEY=(.+)/)
        if (keyMatch && keyMatch[1] && keyMatch[1].trim()) {
            console.info('✓ PostHog API key already exists in .env.local')
            console.info('  `rm hedgebox-dummy/.env.local` or `export FORCE_FETCH_KEY=1` to fetch anew\n')
            return
        }
    }

    const client = new Client({
        host: process.env.PGHOST || 'localhost',
        port: parseInt(process.env.PGPORT || '5432'),
        database: process.env.PGDATABASE || 'posthog',
        user: process.env.PGUSER || 'posthog',
        password: process.env.PGPASSWORD || 'posthog',
        connectionTimeoutMillis: 3000, // A brief timeout to avoid waiting forever
    })

    try {
        await client.connect()
        // Query for the latest team's API token (or you can specify a team_id)
        const result = await client.query(
            process.env.DEMO_TEAM_ID
                ? 'SELECT id, api_token FROM posthog_team WHERE id = $1'
                : 'SELECT id, api_token FROM posthog_team ORDER BY created_at DESC LIMIT 1',
            process.env.DEMO_TEAM_ID ? [process.env.DEMO_TEAM_ID] : []
        )

        if (result.rows.length === 0) {
            console.warn(`⚠ ${process.env.DEMO_TEAM_ID ? `No team found with ID ${process.env.DEMO_TEAM_ID}` : 'No team found'}`)
            console.warn('  Continuing without PostHog API key...\n')
            return
        }

        const { id: teamId, api_token: apiToken } = result.rows[0]

        // Write to .env.local file
        const envPath = path.join(__dirname, '..', '.env.local')
        const envContent = `NEXT_PUBLIC_POSTHOG_KEY=${apiToken}\n`

        fs.writeFileSync(envPath, envContent)
        console.info(`✓ PostHog API key fetched and written to .env.local`)
        console.info(`  Team ID: ${teamId}`)
        console.info(`  API token: ${apiToken}\n`)
    } catch (error) {
        console.warn('⚠ Error fetching PostHog key:', error.message)
        console.warn('  Continuing without PostHog API key...\n')
    } finally {
        await client.end()
    }
}

fetchPostHogKey()
