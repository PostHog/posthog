#!/usr/bin/env node
import fs from 'node:fs'

// The frontend checks used to each post their own PR comment. They now share one
// ci-report comment, so delete any leftover standalone comments once, on the first
// consolidated run, to stop a PR from showing both. Transitional — safe to remove
// after all open PRs have re-run.
const LEGACY_MARKERS = ['<!-- posthog-eager-graph-check -->', '<!-- posthog-bundle-size-check -->']

const token = process.env.GITHUB_TOKEN || process.env.GH_TOKEN
const repo = process.env.GITHUB_REPOSITORY
const eventPath = process.env.GITHUB_EVENT_PATH
if (!token || !repo || !eventPath) {
    console.info('Missing GitHub environment (token/repository/event) — skipping cleanup.')
    process.exit(0)
}
const event = JSON.parse(fs.readFileSync(eventPath, 'utf-8'))
const prNumber = event.pull_request?.number
if (!prNumber) {
    console.info('Not a pull request event — skipping cleanup.')
    process.exit(0)
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
    return response.status === 204 ? null : response.json()
}

try {
    const stale = []
    for (let page = 1; page <= 50; page++) {
        const comments = await gh(`/repos/${repo}/issues/${prNumber}/comments?per_page=100&page=${page}`)
        stale.push(...comments.filter((c) => LEGACY_MARKERS.some((marker) => c.body?.includes(marker))))
        if (comments.length < 100) {
            break
        }
    }
    for (const comment of stale) {
        await gh(`/repos/${repo}/issues/comments/${comment.id}`, { method: 'DELETE' })
        console.info(`Deleted legacy CI comment ${comment.id} on PR #${prNumber}.`)
    }
    if (!stale.length) {
        console.info('No legacy CI comments to delete.')
    }
} catch (err) {
    // Fork PRs run with a read-only token — cleanup is best-effort, never worth a red job.
    console.warn(`Could not clean up legacy CI comments (read-only token on fork PRs?): ${err.message}`)
}
