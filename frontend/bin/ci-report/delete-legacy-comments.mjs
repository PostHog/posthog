#!/usr/bin/env node
import { gh, listPrComments, resolvePrContext } from './update-ci-report.mjs'

// The CI checks used to each post their own PR comment. They now share one
// ci-report comment, so delete any leftover standalone comments once, on the first
// consolidated run, to stop a PR from showing both. Transitional — safe to remove
// after all open PRs have re-run.
const LEGACY_MARKERS = [
    '<!-- posthog-eager-graph-check -->',
    '<!-- posthog-bundle-size-check -->',
    '<!-- mcp-ui-apps-size-report -->',
    '<!-- playwright-report-comment -->',
    '<!-- ch-migration-sql -->',
]

const context = resolvePrContext('cleanup')
if (!context) {
    process.exit(0)
}
const { token, repo, prNumber } = context

try {
    // Same ownership rule as isReportComment in update-ci-report.mjs: every legacy
    // check posted its marker as the first line under the workflow token's identity,
    // and matching on substring alone would let a human comment that quotes or pastes
    // a marker be deleted by CI.
    const stale = (await listPrComments(context)).filter(
        (c) => c.user?.login === 'github-actions[bot]' && LEGACY_MARKERS.some((marker) => c.body?.startsWith(marker))
    )
    for (const comment of stale) {
        await gh(token, `/repos/${repo}/issues/comments/${comment.id}`, { method: 'DELETE' })
        console.info(`Deleted legacy CI comment ${comment.id} on PR #${prNumber}.`)
    }
    if (!stale.length) {
        console.info('No legacy CI comments to delete.')
    }
} catch (err) {
    // Fork PRs run with a read-only token — cleanup is best-effort, never worth a red job.
    console.warn(`Could not clean up legacy CI comments (read-only token on fork PRs?): ${err.message}`)
}
