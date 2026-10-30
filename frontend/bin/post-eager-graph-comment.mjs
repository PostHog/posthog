#!/usr/bin/env node
import { formatBytes, formatDelta } from './ci-report/format.mjs'
import { resolvePrAndBaseReport } from './ci-report/report-files.mjs'
import { postSection } from './ci-report/update-ci-report.mjs'
import {
    GROWTH_APPROVAL_LABEL,
    GROWTH_THRESHOLD_BYTES,
    approvalHint,
    eagerGrowth,
    readPrLabels,
} from './eagerGrowthGate.mjs'

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

const errorCount = report.errors?.length ?? 0
const overBudgetRoots = report.roots.filter((r) => r.overBudget).length
const forbiddenCount = report.roots.reduce((n, r) => n + r.forbiddenHits.length, 0)
const growth = eagerGrowth(report, baseReport)
// null means CI could not read the labels. check-eager-graph.mjs only warns then, so this comment warns too.
const labels = readPrLabels()
const labelsUnknown = labels === null
const growthApproved = !labelsUnknown && labels.includes(GROWTH_APPROVAL_LABEL)
const overThresholdGrowth = growth.filter((g) => g.overThreshold)
const unapprovedGrowth = growthApproved || labelsUnknown ? 0 : overThresholdGrowth.length
const growthWarnings = labelsUnknown ? overThresholdGrowth.length : 0
const anyFailure = Boolean(errorCount || overBudgetRoots || forbiddenCount || growthWarnings)

const problems = [
    unapprovedGrowth && `${unapprovedGrowth} root(s) grew past the limit`,
    overBudgetRoots && `${overBudgetRoots} over budget`,
    forbiddenCount && `${forbiddenCount} forbidden import(s)`,
].filter(Boolean)
const summary = errorCount ? `${errorCount} error(s)` : problems.join(', ') || 'within budget'

function growthLines() {
    const limit = formatBytes(GROWTH_THRESHOLD_BYTES)
    if (!baseReport) {
        return [`ℹ️ No base build to compare against, so the ${limit} growth limit was not checked.`, '']
    }
    const lines = []
    for (const g of growth) {
        const change = formatDelta(g.bytes, g.baseBytes)
        if (!g.overThreshold) {
            lines.push(`🟢 **${g.label}**: ${change}, within the ${limit} growth limit.`)
        } else if (growthApproved) {
            lines.push(
                `✅ **${g.label}**: ${change}, over the ${limit} growth limit. The \`${GROWTH_APPROVAL_LABEL}\` label approves it.`
            )
        } else if (labelsUnknown) {
            lines.push(
                `⚠️ **${g.label}**: ${change}, over the ${limit} growth limit. The pull request labels could not be read, so this does not fail CI.`
            )
        } else {
            lines.push(`❌ **${g.label}**: ${change}, over the ${limit} growth limit. ${approvalHint}`)
        }
    }
    return [...lines, '']
}

const lines = [
    'How much code each root ships on the *eager* path — downloaded and parsed before the surface is interactive. Measured from the esbuild output chunks (post-tree-shake, static imports only); lazy `import()` / `React.lazy` chunks are not counted.',
    '',
    ...growthLines(),
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
    status: unapprovedGrowth ? 'fail' : anyFailure ? 'warn' : 'ok',
    summary,
    body: lines.join('\n'),
})
