#!/usr/bin/env node
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const reportPath = path.resolve(__dirname, '..', 'eager-graph-report.json')

const MARKER = '<!-- posthog-eager-graph-check -->'

const token = process.env.GITHUB_TOKEN || process.env.GH_TOKEN
const repo = process.env.GITHUB_REPOSITORY
const eventPath = process.env.GITHUB_EVENT_PATH

if (!fs.existsSync(reportPath)) {
    console.info('No eager-graph-report.json found — nothing to post (branch may predate the check).')
    process.exit(0)
}
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

const report = JSON.parse(fs.readFileSync(reportPath, 'utf-8'))

function formatBytes(bytes) {
    const abs = Math.abs(bytes)
    if (abs >= 1024 * 1024) {
        return `${(bytes / 1024 / 1024).toFixed(2)} MB`
    }
    if (abs >= 1024) {
        return `${(bytes / 1024).toFixed(1)} kB`
    }
    return `${bytes} B`
}

function formatDelta(bytes, previousBytes) {
    if (previousBytes === undefined) {
        return '_(first run)_'
    }
    const delta = bytes - previousBytes
    if (delta === 0) {
        return 'no change'
    }
    return `${delta > 0 ? '+' : '-'}${formatBytes(Math.abs(delta))}`
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
for (let page = 1; page <= 3 && !existing; page++) {
    const comments = await gh(`/repos/${repo}/issues/${prNumber}/comments?per_page=100&page=${page}`)
    existing = comments.find((c) => c.body?.includes(MARKER)) ?? null
    if (comments.length < 100) {
        break
    }
}

const previous = (() => {
    const match = existing?.body?.match(/<!-- posthog-eager-graph-data (.*?) -->/s)
    try {
        return match ? JSON.parse(match[1]) : {}
    } catch {
        return {}
    }
})()

const anyFailure = report.roots.some((r) => r.overBudget || r.forbiddenHits.length > 0)
const lines = [
    MARKER,
    `<!-- posthog-eager-graph-data ${JSON.stringify(Object.fromEntries(report.roots.map((r) => [r.root, r.bytes])))} -->`,
    `## ${anyFailure ? '❌' : '🕸️'} Eager graph`,
    '',
    "How much code each root forces the browser to download and decode through *static* imports — the regression class total bundle size can't see.",
    '',
    '| Root | Eager closure | Δ this PR run | Budget |',
    '| --- | --- | --- | --- |',
]

for (const r of report.roots) {
    const status = r.overBudget ? '❌ ' : ''
    lines.push(
        `| ${status}**${r.label}**<br/>\`${r.root}\` | ${formatBytes(r.bytes)} · ${r.files.toLocaleString()} files | ${formatDelta(r.bytes, previous[r.root])} | ${budgetBar(r.bytes, r.budgetBytes)} |`
    )
}
lines.push('')

for (const r of report.roots) {
    for (const forbiddenModule of r.forbidden) {
        const hit = r.forbiddenHits.find((h) => h.module === forbiddenModule)
        if (hit) {
            lines.push(`❌ \`${forbiddenModule}\` is statically reachable from \`${r.root}\`:`)
            lines.push('')
            lines.push('```')
            lines.push(hit.chain.join('\n  -> '))
            lines.push('```')
        } else {
            lines.push(`✅ \`${forbiddenModule}\` stays out of \`${r.root}\``)
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
    '<sub>Posted automatically by [check-eager-graph](https://github.com/PostHog/posthog/blob/master/frontend/bin/check-eager-graph.mjs) · sizes are input-source bytes from the esbuild metafile · part of #32479</sub>'
)

const body = lines.join('\n')
if (existing) {
    await gh(`/repos/${repo}/issues/comments/${existing.id}`, { method: 'PATCH', body: JSON.stringify({ body }) })
    console.info(`Updated eager graph comment ${existing.id} on PR #${prNumber}.`)
} else {
    await gh(`/repos/${repo}/issues/${prNumber}/comments`, { method: 'POST', body: JSON.stringify({ body }) })
    console.info(`Posted eager graph comment on PR #${prNumber}.`)
}
