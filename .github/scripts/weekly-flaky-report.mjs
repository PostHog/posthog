// Weekly flaky-test report, posted to #flakey-tests on Monday.
//
// PULL model, sibling of eng-analytics-weekly-digest.mjs: one read of the
// engineering_analytics flaky_tests endpoint, relayed to Slack. The product owns
// the flake signal; this owns cadence, owner attribution, and the relay.
//
//   GHA cron ──> GET /api/projects/:id/engineering_analytics/flaky_tests/ ──> Slack
//
// Endpoint gaps inherited here (backend follow-ups): suites that don't ship junit
// into the span pipeline are invisible, and rerun_passed_count only flows from
// retry-enabled lanes. Master-burst breakage is filtered out client-side.

import { execFileSync } from 'node:child_process'

const HOST = (process.env.POSTHOG_HOST || 'https://us.posthog.com').replace(/\/$/, '')
const PROJECT_ID = process.env.POSTHOG_PROJECT_ID || ''
const API_KEY = process.env.POSTHOG_API_KEY || ''
const SOURCE_ID = process.env.ENG_ANALYTICS_SOURCE_ID || ''
const SLACK_BOT_TOKEN = process.env.SLACK_BOT_TOKEN || ''
const SLACK_CHANNEL = process.env.SLACK_CHANNEL || 'C09ADEV3AJD' // #flakey-tests
const DRY_RUN = ['1', 'true', 'yes'].includes((process.env.DRY_RUN || '').toLowerCase())

const GITHUB_SERVER_URL = process.env.GITHUB_SERVER_URL || 'https://github.com'
const GITHUB_REPOSITORY = process.env.GITHUB_REPOSITORY || 'PostHog/posthog'
const GITHUB_WORKFLOW_REF = process.env.GITHUB_WORKFLOW_REF || ''
const GITHUB_REF_NAME = process.env.GITHUB_REF_NAME || 'master'

const TOP_N = 10

async function api(action, params = {}) {
    const url = new URL(`${HOST}/api/projects/${PROJECT_ID}/engineering_analytics/${action}/`)
    for (const [k, v] of Object.entries(params)) {
        if (v !== undefined && v !== null && v !== '') {
            url.searchParams.set(k, v)
        }
    }
    if (SOURCE_ID) {
        url.searchParams.set('source_id', SOURCE_ID)
    }
    const res = await fetch(url, {
        headers: { Authorization: `Bearer ${API_KEY}` },
        signal: AbortSignal.timeout(150_000),
    })
    const body = await res.text()
    const fail = (detail, retryable) => {
        throw Object.assign(new Error(`${action} -> ${res.status}: ${detail}`), { retryable })
    }
    let parsed
    try {
        parsed = JSON.parse(body)
    } catch {
        fail(`non-JSON response (${body.slice(0, 120)})`, true)
    }
    if (!res.ok) {
        fail(parsed?.detail || body, res.status >= 500 || res.status === 429)
    }
    return parsed
}

const RETRY_ATTEMPTS = 3
const RETRY_DELAY_MS = 30_000

async function apiWithRetry(action, params) {
    for (let attempt = 1; ; attempt++) {
        try {
            return await api(action, params)
        } catch (err) {
            if (err.retryable === false || attempt >= RETRY_ATTEMPTS) {
                throw err
            }
            console.warn(`${err.message} — attempt ${attempt}/${RETRY_ATTEMPTS}, retrying in ${RETRY_DELAY_MS / 1000}s`)
            await new Promise((resolve) => setTimeout(resolve, RETRY_DELAY_MS))
        }
    }
}

// One bad merge is breakage, not flakiness; keep it off the table.
function isMasterBurst(item) {
    return item.failed_count > 0 && item.master_failed_count / item.failed_count >= 0.5 && item.branch_count <= 3
}

// Product suites run from their product dir, so a selector path may be repo- or
// product-relative — suffix-match the tracked index (full even under sparse checkout).
function repoPathResolver() {
    // The tracked-file list is a few MB; the 1MB execFileSync default truncates it.
    const tracked = execFileSync('git', ['ls-files', '*.py'], { encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 })
        .split('\n')
        .filter(Boolean)
    const trackedSet = new Set(tracked)
    const bySuffix = new Map()
    for (const path of tracked) {
        const base = path.split('/').pop()
        if (!bySuffix.has(base)) {
            bySuffix.set(base, [])
        }
        bySuffix.get(base).push(path)
    }
    return (selectorPath) => {
        if (trackedSet.has(selectorPath)) {
            return [selectorPath]
        }
        const matches = (bySuffix.get(selectorPath.split('/').pop()) || []).filter((p) => p.endsWith(`/${selectorPath}`))
        return matches
    }
}

// Ambiguous suffix matches only count when every candidate agrees on the owner.
function resolveOwners(items) {
    const toRepoPaths = repoPathResolver()
    const candidates = new Map() // selectorPath -> repo paths
    for (const item of items) {
        const selectorPath = item.selector.split('::')[0]
        if (!candidates.has(selectorPath)) {
            candidates.set(selectorPath, toRepoPaths(selectorPath))
        }
    }
    const allPaths = [...new Set([...candidates.values()].flat())]
    let resolved = {}
    if (allPaths.length > 0) {
        try {
            const out = execFileSync('python3', ['-m', 'posthog_owners'], {
                encoding: 'utf8',
                input: allPaths.join('\n'),
                env: { ...process.env, PYTHONPATH: 'tools/owners' },
            })
            resolved = JSON.parse(out)
        } catch (err) {
            // Degrade to "unowned" rather than skipping the week's post.
            console.warn(`owners resolution failed — reporting all tests as unowned: ${err.message}`)
        }
    }
    return (item) => {
        const selectorPath = item.selector.split('::')[0]
        const paths = candidates.get(selectorPath) || []
        const owners = new Set(paths.map((p) => (resolved[p]?.owners || [])[0] || 'unowned'))
        const owner = owners.size === 1 ? [...owners][0] : 'unowned'
        return { owner, repoPath: paths.length === 1 ? paths[0] : null }
    }
}

function cell(text) {
    return { type: 'raw_text', text }
}

function mrkdwnCell(text) {
    return { type: 'mrkdwn', text }
}

function shortName(selector) {
    const name = selector.split('::').pop()
    return name.length > 36 ? `${name.slice(0, 35)}…` : name
}

function tableRows(items, ownerFor) {
    return items.map((item) => {
        const { owner, repoPath } = ownerFor(item)
        const name = shortName(item.selector)
        const testCell = repoPath
            ? mrkdwnCell(`<${GITHUB_SERVER_URL}/${GITHUB_REPOSITORY}/blob/master/${repoPath}|${name}>`)
            : cell(name)
        const quarantined = item.xfailed_count > 0 ? ' (quarantined)' : ''
        return [
            testCell,
            cell(owner.replace(/^team-/, '') + quarantined),
            cell(String(item.failed_pr_count)),
            cell(String(item.failed_count)),
        ]
    })
}

function buildBlocks(now, rows) {
    const dateLabel = now.toISOString().slice(0, 10)
    const blocks = [
        { type: 'section', text: { type: 'mrkdwn', text: `*Top ${rows.length} flaky tests — ${dateLabel}* _(backend CI, last 7 days)_` } },
        {
            type: 'table',
            column_settings: [{ align: 'left' }, { align: 'left' }, { align: 'right' }, { align: 'right' }],
            rows: [[cell('test'), cell('owner'), cell('failed PRs'), cell('fails')], ...rows],
        },
        {
            type: 'context',
            elements: [
                {
                    type: 'mrkdwn',
                    text: 'Fix: `/fixing-flaky-tests` · Park 14 days: `hogli test:quarantine add <test id>`',
                },
            ],
        },
    ]
    const workflowPath = GITHUB_WORKFLOW_REF.split('@')[0].replace(`${GITHUB_REPOSITORY}/`, '')
    if (GITHUB_REPOSITORY && workflowPath) {
        const editUrl = `${GITHUB_SERVER_URL}/${GITHUB_REPOSITORY}/edit/${GITHUB_REF_NAME}/${workflowPath}`
        blocks.push({ type: 'context', elements: [{ type: 'mrkdwn', text: `<${editUrl}|edit this workflow>` }] })
    }
    return blocks
}

async function postToSlack(blocks) {
    const res = await fetch('https://slack.com/api/chat.postMessage', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json; charset=utf-8', Authorization: `Bearer ${SLACK_BOT_TOKEN}` },
        body: JSON.stringify({
            channel: SLACK_CHANNEL,
            blocks,
            text: 'Weekly flaky test report', // notification fallback
            unfurl_links: false,
        }),
    })
    const data = await res.json()
    if (!data.ok) {
        throw new Error(`Slack chat.postMessage failed: ${data.error}`)
    }
}

async function main() {
    if (!PROJECT_ID || !API_KEY) {
        console.warn('POSTHOG_PROJECT_ID / POSTHOG_API_KEY not set — skipping report. Wire them to enable.')
        return
    }
    const now = new Date()
    const result = await apiWithRetry('flaky_tests', { date_from: '-7d', limit: 100 })
    const flaky = (result.items || []).filter((item) => !isMasterBurst(item)).slice(0, TOP_N)
    if (flaky.length === 0) {
        // A clean week is a real (great) result; say so instead of going silent.
        console.info('No qualifying flaky tests this week.')
    }
    const ownerFor = resolveOwners(flaky)
    const blocks = buildBlocks(now, tableRows(flaky, ownerFor))
    if (DRY_RUN) {
        console.info(JSON.stringify(blocks, null, 2))
        return
    }
    if (!SLACK_BOT_TOKEN) {
        throw new Error('SLACK_BOT_TOKEN not set on a non-dry run — refusing to silently skip.')
    }
    await postToSlack(blocks)
    console.info(`Posted weekly flaky report to ${SLACK_CHANNEL}.`)
}

main().catch((err) => {
    console.error(err)
    process.exit(1)
})
