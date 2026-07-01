#!/usr/bin/env node
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const frontendDir = path.resolve(__dirname, '..')

const MARKER = '<!-- posthog-eager-graph-check -->'

const token = process.env.GITHUB_TOKEN || process.env.GH_TOKEN
const repo = process.env.GITHUB_REPOSITORY
const eventPath = process.env.GITHUB_EVENT_PATH

if (!token || !repo || !eventPath) {
    console.info('Missing GitHub environment (token/repository/event) — skipping comment.')
    process.exit(0)
}
const event = JSON.parse(fs.readFileSync(eventPath, 'utf-8'))
const prNumber = event.pull_request?.number
if (!prNumber) {
    console.info('Not a pull request event — skipping comment.')
    process.exit(0)
}

// compressed-size-action builds the PR branch and then the base branch in the same
// workspace, so the plain report filename holds the LAST build's (the base's) numbers.
// The PR build's report carries its checkout sha in the filename — that's the one to
// post. The PR build checks out the merge ref, so its sha is GITHUB_SHA; the head sha
// covers non-merge-ref checkouts.
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

// The base build runs last (see the write-side comment in check-eager-graph.mjs),
// so the plain report filename holds the base branch's measurement — the comparison
// baseline, like the compressed-size check's. The embedded sha guards against the
// plain file being this PR's own report (the base build didn't run the check, e.g.
// a base branch that predates it).
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
    console.warn('No base-branch report found — the comment will not show a vs-base delta.')
}

function formatBytes(bytes) {
    const abs = Math.abs(bytes)
    if (abs >= 1024 * 1024) {
        return `${(bytes / 1024 / 1024).toFixed(2)} MiB`
    }
    if (abs >= 1024) {
        return `${(bytes / 1024).toFixed(1)} KiB`
    }
    return `${bytes} B`
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

async function gh(url, options = {}) {
    const response = await fetch(`https://api.github.com${url}`, {
        ...options,
        headers: {
            Authorization: `Bearer ${token}`,
            Accept: 'application/vnd.github+json',
            'Content-Type': 'application/json',
            ...options.headers,
        },
    })
    if (!response.ok) {
        throw new Error(`GitHub API ${options.method || 'GET'} ${url} -> ${response.status}: ${await response.text()}`)
    }
    return response.json()
}

let existing = null
try {
    for (let page = 1; page <= 50 && !existing; page++) {
        const comments = await gh(`/repos/${repo}/issues/${prNumber}/comments?per_page=100&page=${page}`)
        existing = comments.find((c) => c.body?.includes(MARKER)) ?? null
        if (comments.length < 100) {
            break
        }
    }
} catch (err) {
    // Fork PRs run with a read-only token — the comment is a nicety, never worth a red job.
    console.warn(`Could not read PR comments (read-only token on fork PRs?): ${err.message}`)
    process.exit(0)
}

const anyFailure = report.roots.some((r) => r.overBudget || r.forbiddenHits.length > 0) || report.errors?.length > 0

// A comment on every PR teaches people to ignore it — stay silent unless something
// actually moved (or there is a failure to explain). An existing comment from an
// earlier significant push is still updated so it never shows stale numbers.
// A missing baseline is itself significant: with no base report the absolute numbers
// are the signal, and a root absent from (or zero in) the base report is brand new —
// the biggest change there is.
const SIGNIFICANT_CHANGE_PERCENT = 2
const significantChange =
    !baseReport ||
    report.roots.some((r) => {
        const base = baseBytes[r.root]
        if (base === undefined || base === 0) {
            return true
        }
        return (Math.abs(r.bytes - base) / base) * 100 >= SIGNIFICANT_CHANGE_PERCENT
    })
if (!anyFailure && !significantChange && !existing) {
    console.info(
        `No eager graph root changed by >= ${SIGNIFICANT_CHANGE_PERCENT}% vs base and no budget/forbidden failures — not posting a comment.`
    )
    process.exit(0)
}

const lines = [
    MARKER,
    `## ${anyFailure ? '🟡' : '🟢'} Eager graph`,
    '',
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
            lines.push('')
            lines.push('```')
            lines.push(hit.chain.join('\n  -> '))
            lines.push('```')
        } else {
            lines.push(`🟢 \`${forbiddenModule}\` stays out of \`${r.root}\``)
        }
    }
}
lines.push('')

for (const r of report.roots) {
    lines.push(`<details><summary>Largest files eagerly reachable from <code>${r.root}</code></summary>`, '')
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

const body = lines.join('\n')
try {
    if (existing) {
        await gh(`/repos/${repo}/issues/comments/${existing.id}`, { method: 'PATCH', body: JSON.stringify({ body }) })
        console.info(`Updated eager graph comment ${existing.id} on PR #${prNumber}.`)
    } else {
        await gh(`/repos/${repo}/issues/${prNumber}/comments`, { method: 'POST', body: JSON.stringify({ body }) })
        console.info(`Posted eager graph comment on PR #${prNumber}.`)
    }
} catch (err) {
    // Fork PRs run with a read-only token — the comment is a nicety, never worth a red job.
    console.warn(`Could not post eager graph comment (read-only token on fork PRs?): ${err.message}`)
}
