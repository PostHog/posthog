#!/usr/bin/env node

// Discovers which products need testing and builds a GitHub Actions matrix.
//
// Products with < THRESHOLD tests get grouped into one matrix entry
// to avoid spinning up a full Docker stack for a handful of tests.
//
// Input:  LEGACY_CHANGED env var ("true"/"false")
// Output: JSON matrix on stdout, diagnostics on stderr

const { execSync } = require('child_process')
const fs = require('fs')
const path = require('path')

const THRESHOLD = 50

function getTurboTasks() {
    try {
        const raw = execSync('pnpm turbo run backend:test --dry-run=json', {
            encoding: 'utf-8',
            stdio: ['pipe', 'pipe', 'pipe'],
        })
        // Strip non-JSON lines (pnpm/turbo may prepend warnings)
        const jsonStart = raw.indexOf('{')
        if (jsonStart === -1) {
            console.error('No JSON found in turbo output, raw output:')
            console.error(raw.slice(0, 500))
            return []
        }
        const parsed = JSON.parse(raw.slice(jsonStart))
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

function countTestsInDir(dir) {
    let count = 0
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        const full = path.join(dir, entry.name)
        if (entry.isDirectory() && entry.name !== '__pycache__') {
            count += countTestsInDir(full)
        } else if (entry.isFile() && entry.name.endsWith('.py')) {
            const content = fs.readFileSync(full, 'utf-8')
            const matches = content.match(/def test_/g)
            if (matches) {
                count += matches.length
            }
        }
    }
    return count
}

function countTests(product) {
    // Package names use hyphens (batch-exports) but directories use underscores (batch_exports)
    const dirName = product.replace(/-/g, '_')
    const testDir = path.join('products', dirName, 'backend', 'tests')
    if (!fs.existsSync(testDir)) {
        return 0
    }
    return countTestsInDir(testDir)
}

function buildMatrix(products) {
    const matrix = []
    const small = []

    for (const product of products) {
        const count = countTests(product)
        console.error(`  ${product}: ${count} tests`)

        if (count >= THRESHOLD) {
            matrix.push({
                group: product,
                filters: `--filter=@posthog/products-${product}`,
            })
        } else {
            small.push(product)
        }
    }

    if (small.length > 0) {
        matrix.push({
            group: small.join(', '),
            filters: small.map((p) => `--filter=@posthog/products-${p}`).join(' '),
        })
    }

    return matrix
}

const legacyChanged = process.env.LEGACY_CHANGED === 'true'
const tasks = getTurboTasks()
const products = getProducts(tasks, legacyChanged)
console.error(`Products to test: ${JSON.stringify(products)}`)

const matrix = buildMatrix(products)
console.log(JSON.stringify(matrix))
