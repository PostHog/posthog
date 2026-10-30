#!/usr/bin/env node
// Prints the eager graph report as flat event properties, one bytes, files and budget property
// per root, so the posthog-ci-eager-graph event can chart each root as its own series.
import fs from 'node:fs'

const reportPath = process.argv[2]
if (!reportPath || !fs.existsSync(reportPath)) {
    console.error(`No eager graph report at ${reportPath}. Nothing to send.`)
    process.exit(1)
}

const report = JSON.parse(fs.readFileSync(reportPath, 'utf-8'))

// The property key comes from the label text before its explanation, so a reworded
// explanation keeps the series. Renaming the label itself starts a new series.
function rootKey(label) {
    return label
        .split(/[(:]/)[0]
        .trim()
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '_')
        .replace(/^_|_$/g, '')
}

const properties = {
    root_count: report.roots.length,
    over_budget_count: report.roots.filter((r) => r.overBudget).length,
    forbidden_hit_count: report.roots.reduce((n, r) => n + (r.forbiddenHits?.length ?? 0), 0),
    error_count: report.errors?.length ?? 0,
}
for (const r of report.roots) {
    const key = rootKey(r.label)
    properties[`${key}_bytes`] = r.bytes
    properties[`${key}_files`] = r.files
    properties[`${key}_budget_bytes`] = r.budgetBytes
}

console.info(JSON.stringify(properties))
