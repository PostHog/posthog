#!/usr/bin/env node
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { formatBytes } from './ci-report/format.mjs'
import { postSection } from './ci-report/update-ci-report.mjs'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const frontendDir = path.resolve(__dirname, '..')

// The CI bundle-size job builds the PR branch and then the base branch in the same
// workspace, so the plain report filename holds the LAST build's (the base's) numbers.
// The PR build's report carries its checkout sha in the filename — that's the one to
// post. The PR build checks out the merge ref, so its sha is GITHUB_SHA; the head sha
// covers non-merge-ref checkouts.
const eventPath = process.env.GITHUB_EVENT_PATH
const event = eventPath ? JSON.parse(fs.readFileSync(eventPath, 'utf-8')) : {}
const shaCandidates = [process.env.GITHUB_SHA, event.pull_request?.head?.sha].filter(Boolean)
const shaReportPath = shaCandidates
    .map((sha) => path.join(frontendDir, `eager-graph-report-${sha}.json`))
    .find((p) => fs.existsSync(p))
const reportPath = shaReportPath ?? path.join(frontendDir, 'eager-graph-report.json')
if (!fs.existsSync(reportPath)) {
    console.info('No eager graph report found — nothing to post (branch may predate the check).')
    process.exit(0)
}
if (!shaReportPath) {
    console.warn(
        `No report found for shas [${shaCandidates.join(', ')}]; falling back to ${reportPath} — ` +
            `its numbers may be from a different checkout.`
    )
}

const report = JSON.parse(fs.readFileSync(reportPath, 'utf-8'))

// The base build runs last, so the plain report filename holds the base branch's
// measurement — the comparison baseline. The embedded sha guards against the plain file
// being this PR's own report (the base build didn't run the check, e.g. a base branch
// that predates it).
const baseReport = (() => {
    const candidate = path.join(frontendDir, 'eager-graph-report.json')
    if (!fs.existsSync(candidate)) {
        return null
    }
    try {
        const parsed = JSON.parse(fs.readFileSync(candidate, 'utf-8'))
        if (parsed.sha && report.sha && parsed.sha !== report.sha) {
            return parsed
        }
    } catch {
        return null
    }
    return null
})()
const baseBytes = Object.fromEntries((baseReport?.roots ?? []).map((r) => [r.root, r.bytes]))
if (!baseReport) {
    console.warn('No base-branch report found — the section will not show a vs-base delta.')
}

function formatDelta(bytes, baselineBytes) {
    if (baselineBytes === undefined) {
        return '_(no base measurement)_'
    }
    const delta = bytes - baselineBytes
    if (delta === 0) {
        return 'no change'
    }
    const sign = delta > 0 ? '+' : '-'
    const magnitude = `${delta > 0 ? '🔺' : '🟢'} ${sign}${formatBytes(Math.abs(delta))}`
    if (baselineBytes === 0) {
        return `${magnitude} (new)`
    }
    const percent = ((Math.abs(delta) / baselineBytes) * 100).toFixed(1)
    return `${magnitude} (${sign}${percent}%)`
}

function budgetBar(bytes, budgetBytes) {
    const ratio = Math.min(bytes / budgetBytes, 1)
    const filled = Math.round(ratio * 10)
    const bar = '█'.repeat(filled) + '░'.repeat(10 - filled)
    return `\`${bar}\` ${((bytes / budgetBytes) * 100).toFixed(1)}% of ${formatBytes(budgetBytes)}`
}

const anyFailure = report.roots.some((r) => r.overBudget || r.forbiddenHits.length > 0) || report.errors?.length > 0

const overBudgetRoots = report.roots.filter((r) => r.overBudget).length
const forbiddenCount = report.roots.reduce((n, r) => n + r.forbiddenHits.length, 0)
const summary = report.errors?.length
    ? `${report.errors.length} error(s)`
    : overBudgetRoots || forbiddenCount
      ? [overBudgetRoots && `${overBudgetRoots} over budget`, forbiddenCount && `${forbiddenCount} forbidden import(s)`]
            .filter(Boolean)
            .join(', ')
      : 'within budget'

const lines = [
    'How much code each root ships on the *eager* path — downloaded and parsed before the surface is interactive. Measured from the esbuild output chunks (post-tree-shake, static imports only); lazy `import()` / `React.lazy` chunks are not counted.',
    '',
    '| Root | Eager (shipped) | Δ vs base | Budget |',
    '| --- | --- | --- | --- |',
]
for (const r of report.roots) {
    const status = r.overBudget ? '🟡 ' : ''
    lines.push(
        `| ${status}**${r.label}**<br/>\`${r.root}\` | ${formatBytes(r.bytes)} · ${r.files.toLocaleString()} files | ${formatDelta(r.bytes, baseBytes[r.root])} | ${budgetBar(r.bytes, r.budgetBytes)} |`
    )
}
lines.push('')
for (const message of report.errors ?? []) {
    lines.push(`🟡 ${message}`, '')
}
for (const r of report.roots) {
    for (const forbiddenModule of r.forbidden) {
        const hit = r.forbiddenHits.find((h) => h.module === forbiddenModule)
        if (hit) {
            lines.push(`🟡 \`${forbiddenModule}\` ships eagerly from \`${r.root}\`:`)
            lines.push('', '```', hit.chain.join('\n  -> '), '```')
        } else {
            lines.push(`🟢 \`${forbiddenModule}\` stays out of \`${r.root}\``)
        }
    }
}
lines.push('')
for (const r of report.roots) {
    lines.push(`<details><summary>Largest files eagerly shipped from <code>${r.root}</code></summary>`, '')
    lines.push('| Size | File |', '| --- | --- |')
    for (const { file, bytes } of r.largest.slice(0, 10)) {
        lines.push(`| ${formatBytes(bytes)} | \`${file}\` |`)
    }
    lines.push('', '</details>')
}
lines.push('')
lines.push(
    '<sub>Posted automatically by [check-eager-graph](https://github.com/PostHog/posthog/blob/master/frontend/bin/check-eager-graph.mjs) · sizes are eager output bytes (shipped, post-tree-shake) from the esbuild metafile · part of #32479</sub>'
)

await postSection({
    id: 'eager-graph',
    status: anyFailure ? 'warn' : 'ok',
    summary,
    body: lines.join('\n'),
})
