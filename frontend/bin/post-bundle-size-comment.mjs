#!/usr/bin/env node
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const frontendDir = path.resolve(__dirname, '..')

const MARKER = '<!-- posthog-bundle-size-check -->'

// A file whose size moves by less than this is treated as unchanged, matching the
// compressed-size-action `minimum-change-threshold: 1000` this replaces.
const MINIMUM_CHANGE_BYTES = 1000

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

// The base build runs last in the same workspace, so the plain report filename holds the
// base branch's numbers. The PR build's report carries its checkout sha in the filename —
// the PR checks out the merge ref (GITHUB_SHA); head sha covers non-merge-ref checkouts.
const shaCandidates = [process.env.GITHUB_SHA, event.pull_request?.head?.sha].filter(Boolean)
const shaReportPath = shaCandidates
    .map((sha) => path.join(frontendDir, `bundle-size-report-${sha}.json`))
    .find((p) => fs.existsSync(p))
const reportPath = shaReportPath ?? path.join(frontendDir, 'bundle-size-report.json')
if (!fs.existsSync(reportPath)) {
    console.info('No bundle size report found — nothing to post (branch may predate the check).')
    process.exit(0)
}
if (!shaReportPath) {
    console.warn(
        `No report found for shas [${shaCandidates.join(', ')}]; falling back to ${reportPath} — ` +
            `its numbers may be from a different checkout.`
    )
}

const report = JSON.parse(fs.readFileSync(reportPath, 'utf-8'))

// The plain filename is the base measurement only when its sha differs from the PR's —
// otherwise the base build didn't emit a report (base branch predates the check) and the
// plain file is just the PR's own report.
const baseReport = (() => {
    const candidate = path.join(frontendDir, 'bundle-size-report.json')
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
if (!baseReport) {
    console.warn('No base-branch report found — the comment will not show a vs-base delta.')
}
const baseBytes = Object.fromEntries((baseReport?.files ?? []).map((f) => [f.file, f.bytes]))

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
        return `🔺 +${formatBytes(bytes)} (new)`
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

// Only diff per file when there is a baseline. Without one every file looks "new", which
// would flood the comment with the whole manifest and make every delta a bogus increase.
const prFiles = new Map(report.files.map((f) => [f.file, f.bytes]))
const changed = []
if (baseReport) {
    for (const identity of new Set([...prFiles.keys(), ...Object.keys(baseBytes)])) {
        const prBytes = prFiles.get(identity)
        const base = baseBytes[identity]
        const delta = (prBytes ?? 0) - (base ?? 0)
        if (Math.abs(delta) >= MINIMUM_CHANGE_BYTES) {
            changed.push({ identity, prBytes, base, delta })
        }
    }
}
changed.sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta))

const baseTotal = baseReport?.total
const totalDelta = report.total - (baseTotal ?? 0)

const lines = [
    MARKER,
    `## ${baseReport && totalDelta > 0 ? '🔺' : '📦'} Bundle size`,
    '',
    'Uncompressed size of every built `.js` bundle, compared against the base branch.',
    '',
    baseReport
        ? `**Total:** ${formatBytes(report.total)} · ${formatDelta(report.total, baseTotal)}`
        : `**Total:** ${formatBytes(report.total)} _(no base branch measurement to compare against yet)_`,
    '',
]

if (baseReport && changed.length) {
    lines.push('| File | Size | Δ vs base |', '| --- | --- | --- |')
    for (const { identity, prBytes, base } of changed) {
        const size = prBytes === undefined ? '_removed_' : formatBytes(prBytes)
        lines.push(`| \`${identity}\` | ${size} | ${formatDelta(prBytes ?? 0, base)} |`)
    }
    lines.push('')
} else if (baseReport) {
    lines.push(`No file changed by more than ${formatBytes(MINIMUM_CHANGE_BYTES)}.`, '')
}

lines.push(
    '<sub>Posted automatically by [build-bundle-size-report](https://github.com/PostHog/posthog/blob/master/frontend/bin/build-bundle-size-report.mjs) · uncompressed bytes from dist-report</sub>'
)

const body = lines.join('\n')
try {
    if (existing) {
        await gh(`/repos/${repo}/issues/comments/${existing.id}`, { method: 'PATCH', body: JSON.stringify({ body }) })
        console.info(`Updated bundle size comment ${existing.id} on PR #${prNumber}.`)
    } else {
        await gh(`/repos/${repo}/issues/${prNumber}/comments`, { method: 'POST', body: JSON.stringify({ body }) })
        console.info(`Posted bundle size comment on PR #${prNumber}.`)
    }
} catch (err) {
    // Fork PRs run with a read-only token — the comment is a nicety, never worth a red job.
    console.warn(`Could not post bundle size comment (read-only token on fork PRs?): ${err.message}`)
}
