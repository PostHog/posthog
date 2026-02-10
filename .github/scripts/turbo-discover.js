#!/usr/bin/env node

// Discovers which products need testing and builds a GitHub Actions matrix.
//
// Products under SMALL_THRESHOLD duration get grouped into one matrix entry
// to avoid spinning up a full Docker stack for a handful of tests.
// Durations come from .test_durations (maintained by pytest-split).
//
// Input:  LEGACY_CHANGED env var ("true"/"false")
// Output: JSON matrix on stdout, diagnostics on stderr

const { execSync } = require('child_process')
const fs = require('fs')

const SMALL_THRESHOLD_SECONDS = 2 * 60
const TARGET_SHARD_SECONDS = 10 * 60
// Per-product overhead not captured by .test_durations: turbo dispatch, pytest
// collection, Django init. First product pays ~45s, subsequent ~15s; use 20s
// as a conservative average. Durations also underpredict by ~2x because
// pytest-split data was collected under Django Core's shared session.
const SETUP_OVERHEAD_SECONDS = 20
const DURATION_SAFETY_FACTOR = 2
// Tests under these paths need special infrastructure (Temporal server, etc.)
// and are handled by Django CI's dedicated segments — exclude from duration estimates
const EXCLUDED_PATH_SEGMENTS = ['/temporal/']

function getTurboTasks() {
    try {
        // Call turbo directly to avoid pnpm wrapper noise on stdout
        // (pnpm can emit engine warnings like {"node":">=24"} that break JSON parsing)
        const raw = execSync('./node_modules/.bin/turbo run backend:test --dry-run=json', {
            encoding: 'utf-8',
            stdio: ['pipe', 'pipe', 'pipe'],
        })
        const parsed = JSON.parse(raw)
        return parsed.tasks.filter((t) => !/NONEXISTENT/.test(t.command))
    } catch (e) {
        console.error(`turbo dry-run failed: ${e.message}`)
        if (e.stderr) {
            console.error(e.stderr.toString().slice(0, 1000))
        }
        return []
    }
}

function getProducts(tasks, legacyChanged) {
    if (legacyChanged) {
        // Legacy code changed — all products must be tested
        return [...new Set(tasks.map((t) => t.package.replace('@posthog/products-', '')))]
    }
    // Only product files changed — test only cache MISSes
    return [
        ...new Set(
            tasks.filter((t) => t.cache?.status === 'MISS').map((t) => t.package.replace('@posthog/products-', ''))
        ),
    ]
}

function loadTestDurations() {
    try {
        return JSON.parse(fs.readFileSync('.test_durations', 'utf-8'))
    } catch {
        console.error('Warning: .test_durations not found, sharding disabled')
        return null
    }
}

function getProductDuration(product, durations) {
    if (!durations) {
        return 0
    }
    const dirName = product.replace(/-/g, '_')
    const prefix = `products/${dirName}/`
    let total = 0
    for (const [test, dur] of Object.entries(durations)) {
        if (test.startsWith(prefix) && !EXCLUDED_PATH_SEGMENTS.some((seg) => test.includes(seg))) {
            total += dur
        }
    }
    return total
}

function packSmallProducts(products, durations) {
    const buckets = []
    let current = []
    let currentDuration = 0

    for (const product of products) {
        const effective = getProductDuration(product, durations) * DURATION_SAFETY_FACTOR + SETUP_OVERHEAD_SECONDS
        if (current.length > 0 && currentDuration + effective > TARGET_SHARD_SECONDS) {
            buckets.push(current)
            current = []
            currentDuration = 0
        }
        current.push(product)
        currentDuration += effective
    }
    if (current.length > 0) {
        buckets.push(current)
    }
    return buckets
}

function buildMatrix(products, durations) {
    const matrix = []
    const small = []

    for (const product of products) {
        const duration = getProductDuration(product, durations)
        const shards = duration > TARGET_SHARD_SECONDS ? Math.ceil(duration / TARGET_SHARD_SECONDS) : 1
        console.error(`  ${product}: ${(duration / 60).toFixed(1)} min, ${shards} shard(s)`)
        const filters = `--filter=@posthog/products-${product}`

        if (duration < SMALL_THRESHOLD_SECONDS) {
            small.push(product)
        } else if (shards > 1) {
            for (let i = 1; i <= shards; i++) {
                matrix.push({
                    group: `${product} (${i}/${shards})`,
                    filters,
                    pytest_args: `-- --splits ${shards} --group ${i} --splitting-algorithm duration_based_chunks`,
                })
            }
        } else {
            matrix.push({ group: product, filters, pytest_args: '' })
        }
    }

    for (const bucket of packSmallProducts(small, durations)) {
        matrix.push({
            group: bucket.join(', '),
            filters: bucket.map((p) => `--filter=@posthog/products-${p}`).join(' '),
            pytest_args: '',
        })
    }

    return matrix
}

const legacyChanged = process.env.LEGACY_CHANGED === 'true'
const tasks = getTurboTasks()
const products = getProducts(tasks, legacyChanged)
console.error(`Products to test: ${JSON.stringify(products)}`)

const durations = loadTestDurations()
// eslint-disable-next-line no-console
process.stdout.write(JSON.stringify(buildMatrix(products, durations)) + '\n')
