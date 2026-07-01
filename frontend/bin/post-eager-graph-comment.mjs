#!/usr/bin/env node
import { formatBytes, formatDelta } from './ci-report/format.mjs'
import { resolvePrAndBaseReport } from './ci-report/report-files.mjs'
import { postSection } from './ci-report/update-ci-report.mjs'

const resolved = resolvePrAndBaseReport('eager-graph-report', 'eager graph')
if (!resolved) {
    process.exit(0)
}
const { report, baseReport } = resolved
const baseBytes = Object.fromEntries((baseReport?.roots ?? []).map((r) => [r.root, r.bytes]))

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
        `| ${status}**${r.label}**<br/>\`${r.root}\` | ${formatBytes(r.bytes)} · ${r.files.toLocaleString()} files | ${formatDelta(r.bytes, baseBytes[r.root], { noBaseline: '_(no base measurement)_' })} | ${budgetBar(r.bytes, r.budgetBytes)} |`
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
