#!/usr/bin/env node
import { spawnSync } from 'child_process'
import { readFileSync } from 'fs'
import os from 'os'
import path from 'path'
import { fileURLToPath } from 'url'

import { tsgoPlan } from './typescriptCheckPlan.mjs'

const WATCHDOG_RATIO = 0.85
const frontendDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')

function readNumber(file, key) {
    try {
        const text = readFileSync(file, 'utf8')
        const value = key
            ? text
                  .split('\n')
                  .map((line) => line.split(/\s+/))
                  .find(([name]) => name === key)?.[1]
            : text
        return value === undefined ? null : Number(value.trim())
    } catch {
        return null
    }
}

function cgroupHeadroomBytes(dir, limitFile, currentFile, inactiveKey) {
    const limit = readNumber(`${dir}/${limitFile}`)
    const current = readNumber(`${dir}/${currentFile}`)
    if (!limit || !current || limit > 2 ** 50) {
        return null
    }
    return WATCHDOG_RATIO * limit - current + (readNumber(`${dir}/memory.stat`, inactiveKey) ?? 0)
}

function meminfoHeadroomBytes() {
    const total = readNumber('/proc/meminfo', 'MemTotal:')
    const available = readNumber('/proc/meminfo', 'MemAvailable:')
    if (!total || available === null || Number.isNaN(available)) {
        return null
    }
    return (WATCHDOG_RATIO * total - (total - available)) * 1024
}

function headroomBytes() {
    if (process.platform !== 'linux') {
        return null
    }
    return (
        cgroupHeadroomBytes('/sys/fs/cgroup', 'memory.max', 'memory.current', 'inactive_file') ??
        cgroupHeadroomBytes(
            '/sys/fs/cgroup/memory',
            'memory.limit_in_bytes',
            'memory.usage_in_bytes',
            'total_inactive_file'
        ) ??
        meminfoHeadroomBytes() ??
        os.freemem() - (1 - WATCHDOG_RATIO) * os.totalmem()
    )
}

const plan = tsgoPlan(headroomBytes())
if (plan.mode === 'refuse') {
    console.error(plan.message)
    process.exit(75)
}
const constrained = plan.mode === 'constrained'
const args = ['--noEmit', ...(constrained ? ['--checkers', '1'] : []), ...process.argv.slice(2)]
let env = process.env
if (constrained) {
    env = { GOMEMLIMIT: plan.goMemLimit, ...process.env }
    console.info(
        `${plan.headroomGib} GiB of memory headroom: running tsgo with one checker and GOMEMLIMIT=${env.GOMEMLIMIT}.`
    )
}

const result = spawnSync('tsgo', args, { cwd: frontendDir, env, stdio: 'inherit' })
if (result.error) {
    console.error(`Failed to run tsgo: ${result.error.message}`)
    process.exit(1)
}
if (result.status === 0) {
    console.info('No errors reported by tsgo.')
}
process.exit(result.status ?? 1)
