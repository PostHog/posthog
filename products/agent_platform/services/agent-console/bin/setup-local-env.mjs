#!/usr/bin/env node
/**
 * One-shot local dev setup for the agent console.
 *
 * Idempotent — safe to re-run. What it does:
 *   1. Calls the `setup_oauth_for_agent_console` Django management
 *      command (via `flox activate -- python manage.py ...`) and
 *      parses the JSON output to get `client_id` + `client_secret`.
 *   2. Reads any existing `.env.local`, merges in the OAuth creds.
 *   3. Writes `.env.local` back out.
 *
 * The cookie sealer (`OAUTH_COOKIE_SECRET`) and URL defaults are no
 * longer materialized into `.env.local` — `src/lib/config.ts` supplies
 * deterministic dev defaults for them via zod. Override either by
 * setting the env var explicitly.
 *
 * Run from the agent-console directory or anywhere — it cd's to the
 * package root by `import.meta.url`.
 *
 * Existing values you've already set are preserved.
 */

import { spawn } from 'node:child_process'
import { promises as fs } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const CONSOLE_ROOT = path.resolve(HERE, '..')
const REPO_ROOT = path.resolve(CONSOLE_ROOT, '../../../..')
const ENV_FILE = path.join(CONSOLE_ROOT, '.env.local')

async function main() {
    const { clientId, clientSecret } = await runDjango()

    const existing = await readEnvFile(ENV_FILE)
    const merged = { ...existing }

    merged.POSTHOG_OAUTH_CLIENT_ID = clientId
    if (clientSecret) {
        merged.POSTHOG_OAUTH_CLIENT_SECRET = clientSecret
    } else if (!merged.POSTHOG_OAUTH_CLIENT_SECRET) {
        throw new Error(
            'Django returned no client_secret (--keep-secret used?) and none exists in .env.local. ' +
                'Re-run without --keep-secret to rotate.'
        )
    }

    await writeEnvFile(ENV_FILE, merged)
}

function runDjango() {
    return new Promise((resolve, reject) => {
        // Run via flox so the project's Python env + .env vars are loaded.
        const args = [
            'activate',
            '--',
            'python',
            'manage.py',
            'setup_oauth_for_agent_console',
            '--json',
            '--verbosity',
            '0',
        ]
        const child = spawn('flox', args, { cwd: REPO_ROOT })
        let stdout = ''
        let stderr = ''
        child.stdout.on('data', (chunk) => {
            stdout += chunk.toString('utf8')
        })
        child.stderr.on('data', (chunk) => {
            stderr += chunk.toString('utf8')
        })
        child.on('error', reject)
        child.on('close', (code) => {
            if (code !== 0) {
                reject(new Error(`setup_oauth_for_agent_console exited ${code}\n${stderr}`))
                return
            }
            // The command may print Django startup banners; keep only the
            // last line, which is the JSON object we emitted.
            const lastJsonLine = stdout
                .trim()
                .split('\n')
                .reverse()
                .find((l) => l.startsWith('{'))
            if (!lastJsonLine) {
                reject(new Error(`Could not find JSON in setup_oauth_for_agent_console output:\n${stdout}`))
                return
            }
            try {
                resolve(JSON.parse(lastJsonLine))
            } catch (err) {
                reject(new Error(`Failed to parse JSON from setup_oauth_for_agent_console: ${err.message}`))
            }
        })
    })
}

async function readEnvFile(file) {
    try {
        const raw = await fs.readFile(file, 'utf8')
        const out = {}
        for (const line of raw.split(/\r?\n/)) {
            const trimmed = line.trim()
            if (!trimmed || trimmed.startsWith('#')) {
                continue
            }
            const eq = trimmed.indexOf('=')
            if (eq === -1) {
                continue
            }
            const key = trimmed.slice(0, eq).trim()
            let value = trimmed.slice(eq + 1).trim()
            if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
                value = value.slice(1, -1)
            }
            out[key] = value
        }
        return out
    } catch (err) {
        if (err.code === 'ENOENT') {
            return {}
        }
        throw err
    }
}

async function writeEnvFile(file, kv) {
    // Preserve a stable order. Anything we didn't predefine gets
    // appended at the bottom in insertion order.
    const orderedKeys = ['POSTHOG_OAUTH_CLIENT_ID', 'POSTHOG_OAUTH_CLIENT_SECRET']
    const seen = new Set()
    const lines = []
    for (const key of orderedKeys) {
        if (kv[key] != null) {
            lines.push(`${key}=${kv[key]}`)
            seen.add(key)
        }
    }
    for (const [key, value] of Object.entries(kv)) {
        if (seen.has(key)) {
            continue
        }
        lines.push(`${key}=${value}`)
    }
    await fs.writeFile(file, lines.join('\n') + '\n', 'utf8')
}

main().catch((err) => {
    console.error('setup-local-env failed:', err.message)
    process.exit(1)
})
