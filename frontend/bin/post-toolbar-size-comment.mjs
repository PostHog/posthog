#!/usr/bin/env node
import { formatBytes, formatDelta } from './ci-report/format.mjs'
import { resolvePrAndBaseReport } from './ci-report/report-files.mjs'
import { postSection } from './ci-report/update-ci-report.mjs'

const resolved = resolvePrAndBaseReport('toolbar-size-report', 'toolbar bundle')
if (!resolved) {
    process.exit(0)
}
const { report, baseReport } = resolved

function budgetBar(bytes, budgetBytes) {
    const ratio = Math.min(bytes / budgetBytes, 1)
    const filled = Math.round(ratio * 10)
    const bar = '█'.repeat(filled) + '░'.repeat(10 - filled)
    return `\`${bar}\` ${((bytes / budgetBytes) * 100).toFixed(1)}% of ${formatBytes(budgetBytes)}`
}

const oversizeCount = report.oversizeFiles?.length ?? 0
const cssIncompleteCount = report.cssIncomplete?.length ?? 0
const loaderOverBudget = Boolean(report.loaderOverBudget)
const anyFailure = Boolean(report.overBudget || oversizeCount || loaderOverBudget || cssIncompleteCount)
const summary = report.overBudget
    ? `eager ${formatBytes(report.eagerBytes)} over budget`
    : loaderOverBudget
      ? `loader ${formatBytes(report.loaderBytes)} over budget`
      : oversizeCount
        ? `${oversizeCount} file(s) over the CloudFront gzip limit`
        : cssIncompleteCount
          ? `${cssIncompleteCount} chunk stylesheet(s) missing from the entry`
          : `eager ${formatBytes(report.eagerBytes)} within budget`

const lines = [
    'What the toolbar ships to customer pages, measured from the esbuild *output* (minified, post-tree-shake). ' +
        'The eager set is the entry plus everything statically imported from it — fetched before any feature runs; ' +
        `deferred chunks load lazily. The eager guardrail is ${formatBytes(report.budgetBytes)}. ` +
        'Each output file must also stay below 10 MB, ' +
        'where CloudFront stops compressing it. The module boundary is enforced separately by ' +
        '[check-toolbar-graph](https://github.com/PostHog/posthog/blob/master/frontend/bin/check-toolbar-graph.mjs).',
    '',
    '| Metric | Size | Δ vs base | Budget |',
    '| --- | --- | --- | --- |',
    `| ${report.overBudget ? '🟡 ' : ''}**Eager (shipped)**<br/>entry + static imports | ${formatBytes(report.eagerBytes)} · ${report.eagerFiles.toLocaleString()} files | ${formatDelta(report.eagerBytes, baseReport?.eagerBytes, { noBaseline: '_(no base measurement)_' })} | ${budgetBar(report.eagerBytes, report.budgetBytes)} |`,
    `| **Deferred (lazy)** | ${formatBytes(report.lazyBytes)} · ${report.lazyFiles.toLocaleString()} files | ${formatDelta(report.lazyBytes, baseReport?.lazyBytes, { noBaseline: '_(no base measurement)_' })} | _n/a — loads on demand_ |`,
    `| ${loaderOverBudget ? '🟡 ' : ''}**Loader** \`dist/toolbar.js\` | ${formatBytes(report.loaderBytes)} | ${formatDelta(report.loaderBytes, baseReport?.loaderBytes, { noBaseline: '_(no base measurement)_' })} | ${budgetBar(report.loaderBytes, report.loaderBudget)} |`,
]
lines.push('')

if (report.overBudget) {
    lines.push(
        `🟡 Eager toolbar output is ${formatBytes(report.eagerBytes)}, over the ${formatBytes(report.budgetBytes)} budget. ` +
            'Something newly reachable through static imports — lazy-load it (`import()`) or cut the import edge.',
        ''
    )
}
if (loaderOverBudget) {
    lines.push(
        `🟡 Loader \`dist/toolbar.js\` is ${formatBytes(report.loaderBytes)}, over the ${formatBytes(report.loaderBudget)} budget. ` +
            'It ships on every toolbar load before anything runs — app code belongs in the ESM entry.',
        ''
    )
}
for (const { file, bytes } of report.oversizeFiles ?? []) {
    lines.push(
        `🟡 \`${file}\` is ${formatBytes(bytes)}, over the ${formatBytes(report.maxFileBytes)} CloudFront gzip limit — split it further.`,
        ''
    )
}
for (const { file, missing } of report.cssIncomplete ?? []) {
    lines.push(
        `🟡 \`${file}\` contains styles missing from the entry stylesheet (${missing.join(', ')}) — ` +
            'they would never load into the shadow root. Import them statically.',
        ''
    )
}

lines.push('<details><summary>Largest eagerly-shipped chunks</summary>', '')
lines.push('| Size | File |', '| --- | --- |')
for (const { file, bytes } of (report.largest ?? []).slice(0, 10)) {
    lines.push(`| ${formatBytes(bytes)} | \`${file}\` |`)
}
lines.push('', '</details>', '')
lines.push(
    '<sub>Posted automatically by [check-toolbar-size](https://github.com/PostHog/posthog/blob/master/frontend/bin/check-toolbar-size.mjs) · sizes are toolbar output bytes (shipped, post-tree-shake) from the esbuild metafile</sub>'
)

await postSection({
    id: 'toolbar-size',
    status: anyFailure ? 'warn' : 'ok',
    summary,
    body: lines.join('\n'),
})
