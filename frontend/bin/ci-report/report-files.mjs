import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const frontendDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..')

// The CI bundle-size job builds the PR branch and then the base branch in the same
// workspace, so the plain report filename holds the LAST build's (the base's) numbers.
// The PR build's report carries its checkout sha in the filename — the PR checks out the
// merge ref (GITHUB_SHA); head sha covers non-merge-ref checkouts. The base build runs
// last, so the plain file doubles as the baseline, but only when its sha differs from the
// PR's (otherwise the base build didn't emit a report — a base branch that predates the
// check — and the plain file is just the PR's own).
export function resolvePrAndBaseReport(basename, label) {
    const eventPath = process.env.GITHUB_EVENT_PATH
    const event = eventPath ? JSON.parse(fs.readFileSync(eventPath, 'utf-8')) : {}
    const shaCandidates = [process.env.GITHUB_SHA, event.pull_request?.head?.sha].filter(Boolean)
    const plainPath = path.join(frontendDir, `${basename}.json`)
    const shaReportPath = shaCandidates
        .map((sha) => path.join(frontendDir, `${basename}-${sha}.json`))
        .find((p) => fs.existsSync(p))
    const reportPath = shaReportPath ?? plainPath
    if (!fs.existsSync(reportPath)) {
        console.info(`No ${label} report found — nothing to post (branch may predate the check).`)
        return null
    }
    if (!shaReportPath) {
        console.warn(
            `No report found for shas [${shaCandidates.join(', ')}]; falling back to ${reportPath} — ` +
                `its numbers may be from a different checkout.`
        )
    }

    const report = JSON.parse(fs.readFileSync(reportPath, 'utf-8'))
    let baseReport = null
    if (fs.existsSync(plainPath)) {
        try {
            const parsed = JSON.parse(fs.readFileSync(plainPath, 'utf-8'))
            if (parsed.sha && report.sha && parsed.sha !== report.sha) {
                baseReport = parsed
            }
        } catch {
            baseReport = null
        }
    }
    if (!baseReport) {
        console.warn(`No base-branch report found — the ${label} section will not show a vs-base delta.`)
    }
    return { report, baseReport }
}
