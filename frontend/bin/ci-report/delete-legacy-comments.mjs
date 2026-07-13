#!/usr/bin/env node
import { gh, listPrComments, resolvePrContext } from './update-ci-report.mjs'

// The frontend checks used to each post their own PR comment. They now share one
// ci-report comment, so delete any leftover standalone comments once, on the first
// consolidated run, to stop a PR from showing both. Transitional — safe to remove
// after all open PRs have re-run.
const LEGACY_MARKERS = ['<!-- posthog-eager-graph-check -->', '<!-- posthog-bundle-size-check -->']

const context = resolvePrContext('cleanup')
if (!context) {
    process.exit(0)
}
const { token, repo, prNumber } = context

try {
    const stale = (await listPrComments(context)).filter((c) =>
        LEGACY_MARKERS.some((marker) => c.body?.includes(marker))
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
