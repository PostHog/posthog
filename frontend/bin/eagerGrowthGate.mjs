import fs from 'node:fs'

import { AUTHENTICATED_SHELL, LOGGED_OUT_BOOT } from './bootEntries.mjs'

// The absolute budgets in check-eager-graph.mjs stay as a warn-only backstop, because many
// pull requests that each stay under this threshold still add up.
export const GROWTH_GATED_ROOTS = [LOGGED_OUT_BOOT.join(' + '), AUTHENTICATED_SHELL]
export const GROWTH_THRESHOLD_BYTES = 20 * 1024
export const GROWTH_APPROVAL_LABEL = 'eager-growth-approved'

// A plain report with the pull request's own sha means the base build wrote nothing.
export function readBaseReport(baseReportPath, report) {
    if (!baseReportPath || !fs.existsSync(baseReportPath)) {
        return null
    }
    try {
        const baseReport = JSON.parse(fs.readFileSync(baseReportPath, 'utf-8'))
        return baseReport.sha && report.sha && baseReport.sha !== report.sha ? baseReport : null
    } catch {
        return null
    }
}

// null means the labels are unknown, which makes the gate warn instead of fail.
export function readPrLabels(labelsFilePath = process.env.PR_LABELS_FILE) {
    if (!labelsFilePath || !fs.existsSync(labelsFilePath)) {
        return null
    }
    return fs
        .readFileSync(labelsFilePath, 'utf-8')
        .split('\n')
        .map((label) => label.trim())
        .filter(Boolean)
}

export function eagerGrowth(report, baseReport) {
    if (!baseReport) {
        return []
    }
    const baseBytes = new Map((baseReport.roots ?? []).map((r) => [r.root, r.bytes]))
    return report.roots
        .filter((r) => GROWTH_GATED_ROOTS.includes(r.root) && baseBytes.has(r.root))
        .map((r) => {
            const delta = r.bytes - baseBytes.get(r.root)
            return {
                root: r.root,
                label: r.label,
                bytes: r.bytes,
                baseBytes: baseBytes.get(r.root),
                delta,
                overThreshold: delta > GROWTH_THRESHOLD_BYTES,
            }
        })
}

export const approvalHint =
    `Make the new import lazy (React.lazy or a dynamic import()). If the growth is intended, ` +
    `add the '${GROWTH_APPROVAL_LABEL}' label to the pull request and re-run the "Frontend checks" job.`
