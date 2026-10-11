#!/usr/bin/env node
import { spawnSync } from 'child_process'
import path from 'path'
import { fileURLToPath } from 'url'

const frontendDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')

// A cloud task sandbox runs the dev stack next to this check, and the default tsgo run
// uses enough memory to make the sandbox memory watchdog stop it.
// One checker and a soft Go heap limit keep the whole sandbox under that limit.
const inCloudTask = Boolean(process.env.POSTHOG_TASK_RUN_ID)
const args = ['--noEmit', ...(inCloudTask ? ['--checkers', '1'] : []), ...process.argv.slice(2)]
const env = inCloudTask ? { GOMEMLIMIT: '8GiB', ...process.env } : process.env

const result = spawnSync('tsgo', args, { cwd: frontendDir, env, stdio: 'inherit' })

if (result.error) {
    console.error(`Failed to run tsgo: ${result.error.message}`)
    process.exit(1)
}
if (result.status === 0) {
    console.info('No errors reported by tsgo.')
}
process.exit(result.status ?? 1)
