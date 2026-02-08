#!/usr/bin/env node
/**
 * Compare Jest JSON benchmark results between two test runs.
 *
 * Usage:
 *   node compare-jest-benchmarks.js <before.json> <after.json> [--filter=file1,file2,...]
 *
 * Example:
 *   # Run tests before changes:
 *   pnpm test -- --json --outputFile=jest-results-before.json
 *
 *   # Make your changes, then run tests again:
 *   pnpm test -- --json --outputFile=jest-results-after.json
 *
 *   # Compare results:
 *   node scripts/compare-jest-benchmarks.js jest-results-before.json jest-results-after.json
 *
 *   # Or filter to specific files:
 *   node scripts/compare-jest-benchmarks.js before.json after.json --filter=myLogic.test.ts,myComponent.test.tsx
 */

const fs = require('fs')

const args = process.argv.slice(2)
const beforeFile = args[0]
const afterFile = args[1]
const filterArg = args.find((a) => a.startsWith('--filter='))
const filterFiles = filterArg ? filterArg.replace('--filter=', '').split(',') : null

if (!beforeFile || !afterFile) {
    console.error('Usage: node compare-jest-benchmarks.js <before.json> <after.json> [--filter=file1,file2,...]')
    process.exit(1)
}

const before = JSON.parse(fs.readFileSync(beforeFile, 'utf8'))
const after = JSON.parse(fs.readFileSync(afterFile, 'utf8'))

// Calculate per-suite durations
function getSuiteDurations(results) {
    const durations = {}
    for (const suite of results.testResults) {
        const name = suite.name.replace(/.*\/(frontend|products)\//, '')
        const totalDuration = suite.assertionResults.reduce((sum, t) => sum + (t.duration || 0), 0)
        durations[name] = {
            testCount: suite.assertionResults.length,
            totalDuration,
            wallTime: suite.endTime - suite.startTime,
        }
    }
    return durations
}

const beforeDurations = getSuiteDurations(before)
const afterDurations = getSuiteDurations(after)

// Get all files to compare
let filesToCompare = Object.keys(beforeDurations).filter((f) => afterDurations[f])

if (filterFiles) {
    filesToCompare = filesToCompare.filter((f) => filterFiles.some((filter) => f.includes(filter)))
}

// Build comparisons
const comparisons = []
let totalBeforeDuration = 0
let totalAfterDuration = 0

for (const file of filesToCompare) {
    const b = beforeDurations[file]
    const a = afterDurations[file]

    const durationDiff = a.totalDuration - b.totalDuration
    totalBeforeDuration += b.totalDuration
    totalAfterDuration += a.totalDuration

    comparisons.push({
        file,
        beforeDuration: b.totalDuration,
        afterDuration: a.totalDuration,
        durationDiff,
        percentChange: ((durationDiff / b.totalDuration) * 100).toFixed(1),
        beforeTests: b.testCount,
        afterTests: a.testCount,
    })
}

// Sort by improvement (biggest improvements first)
comparisons.sort((a, b) => a.durationDiff - b.durationDiff)

// Output

const improved = comparisons.filter((c) => c.durationDiff < 0)
const regressed = comparisons.filter((c) => c.durationDiff > 0)
const unchanged = comparisons.filter((c) => c.durationDiff === 0)

if (improved.length > 0) {
    console.log('\n✅ IMPROVED (' + improved.length + ' files):')
    for (const c of improved) {
        console.log(`  ${c.file}: ${c.beforeDuration}ms → ${c.afterDuration}ms (${c.percentChange}%)`)
    }
}

if (regressed.length > 0) {
    console.log('\n⚠️  REGRESSED (' + regressed.length + ' files):')
    for (const c of regressed) {
        console.log(`  ${c.file}: ${c.beforeDuration}ms → ${c.afterDuration}ms (+${c.percentChange}%)`)
    }
}

if (unchanged.length > 0) {
    console.log('\n➖ UNCHANGED (' + unchanged.length + ' files)')
}

// Summary
console.log('\n📊 SUMMARY:')
console.log(`  Files compared: ${filesToCompare.length}`)

const totalDiff = totalAfterDuration - totalBeforeDuration
const totalPercent = ((totalDiff / totalBeforeDuration) * 100).toFixed(1)

if (totalDiff < 0) {
    console.log(`  Total duration: ${totalBeforeDuration}ms → ${totalAfterDuration}ms (${totalPercent}%) 🎉`)
} else if (totalDiff > 0) {
    console.log(`  Total duration: ${totalBeforeDuration}ms → ${totalAfterDuration}ms (+${totalPercent}%) ⚠️`)
} else {
    console.log(`  Total duration: ${totalBeforeDuration}ms (no change)`)
}
