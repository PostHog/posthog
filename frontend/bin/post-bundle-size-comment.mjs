#!/usr/bin/env node
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { deltaStatus, formatBytes, formatDelta } from './ci-report/format.mjs'
import { postSection } from './ci-report/update-ci-report.mjs'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const frontendDir = path.resolve(__dirname, '..')

// A file whose size moves by less than this is treated as unchanged, matching the
// compressed-size-action `minimum-change-threshold: 1000` this replaces.
const MINIMUM_CHANGE_BYTES = 1000

// The base build runs last in the same workspace, so the plain report filename holds the
// base branch's numbers. The PR build's report carries its checkout sha in the filename —
// the PR checks out the merge ref (GITHUB_SHA); head sha covers non-merge-ref checkouts.
const eventPath = process.env.GITHUB_EVENT_PATH
const event = eventPath ? JSON.parse(fs.readFileSync(eventPath, 'utf-8')) : {}
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
    console.warn('No base-branch report found — the section will not show a vs-base delta.')
}
const baseBytes = Object.fromEntries((baseReport?.files ?? []).map((f) => [f.file, f.bytes]))

// Only diff per file when there is a baseline. Without one every file looks "new", which
// would flood the section with the whole manifest and make every delta a bogus increase.
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

const baseTotal = baseReport?.total ?? null
const totalDelta = report.total - (baseTotal ?? 0)

const lines = [
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

await postSection({
    id: 'bundle-size',
    status: deltaStatus(totalDelta, baseTotal !== null),
    summary: baseTotal !== null ? formatDelta(report.total, baseTotal) : 'no base branch to compare',
    body: lines.join('\n'),
})
