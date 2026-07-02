#!/usr/bin/env node
import { formatBytes, formatDelta, totalComparison } from './ci-report/format.mjs'
import { resolvePrAndBaseReport } from './ci-report/report-files.mjs'
import { postSection } from './ci-report/update-ci-report.mjs'

// A file whose size moves by less than this is treated as unchanged, matching the
// compressed-size-action `minimum-change-threshold: 1000` this replaces.
const MINIMUM_CHANGE_BYTES = 1000

const resolved = resolvePrAndBaseReport('bundle-size-report', 'bundle size')
if (!resolved) {
    process.exit(0)
}
const { report, baseReport } = resolved
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

const total = totalComparison(report.total, baseReport?.total ?? null)

const lines = [
    'Uncompressed size of every built `.js` bundle, compared against the base branch.',
    '',
    total.totalLine,
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
    status: total.status,
    summary: total.summary,
    body: lines.join('\n'),
})
