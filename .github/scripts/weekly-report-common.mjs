// Shared machinery for the weekly report scripts (weekly-flaky-report.mjs,
// weekly-slow-tests-report.mjs, weekly-mcp-tool-health-report.mjs): PostHog API plumbing,
// HogQL, repo path and owner resolution, Slack table cells, the Slack post, and the per-team
// delivery. Everything here reads the same environment every workflow sets, so each report owns
// only its signal and its table.

import { execFileSync } from 'node:child_process'

export const HOST = (process.env.POSTHOG_HOST || 'https://us.posthog.com').replace(/\/$/, '')
export const PROJECT_ID = process.env.POSTHOG_PROJECT_ID || ''
export const API_KEY = process.env.POSTHOG_API_KEY || ''
export const SLACK_BOT_TOKEN = process.env.SLACK_BOT_TOKEN || ''
export const SLACK_CHANNEL = process.env.SLACK_CHANNEL || 'C09ADEV3AJD' // #flakey-tests
export const DRY_RUN = ['1', 'true', 'yes'].includes((process.env.DRY_RUN || '').toLowerCase())

export const GITHUB_SERVER_URL = process.env.GITHUB_SERVER_URL || 'https://github.com'
export const GITHUB_REPOSITORY = process.env.GITHUB_REPOSITORY || 'PostHog/posthog'
export const GITHUB_WORKFLOW_REF = process.env.GITHUB_WORKFLOW_REF || ''
export const GITHUB_REF_NAME = process.env.GITHUB_REF_NAME || 'master'

const RETRY_ATTEMPTS = 3
const RETRY_DELAY_MS = 30_000

async function request(url, options, label) {
    const res = await fetch(url, { ...options, signal: AbortSignal.timeout(150_000) })
    const body = await res.text()
    const fail = (detail, retryable) => {
        throw Object.assign(new Error(`${label} -> ${res.status}: ${detail}`), { retryable })
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

async function withRetry(fn) {
    for (let attempt = 1; ; attempt++) {
        try {
            return await fn()
        } catch (err) {
            if (err.retryable === false || attempt >= RETRY_ATTEMPTS) {
                throw err
            }
            console.warn(`${err.message} — attempt ${attempt}/${RETRY_ATTEMPTS}, retrying in ${RETRY_DELAY_MS / 1000}s`)
            await new Promise((resolve) => setTimeout(resolve, RETRY_DELAY_MS))
        }
    }
}

export const AUTH_HEADERS = { Authorization: `Bearer ${API_KEY}` }

// `values` bind through HogQL's {placeholder} syntax, escaped server-side — never
// concatenate attacker-controlled test ids into the query source.
export function hogql(query, values) {
    return withRetry(() =>
        request(
            `${HOST}/api/projects/${PROJECT_ID}/query/`,
            {
                method: 'POST',
                headers: { ...AUTH_HEADERS, 'Content-Type': 'application/json' },
                body: JSON.stringify({ query: { kind: 'HogQLQuery', query, values } }),
            },
            'query'
        )
    )
}

export function requestPosthog(url, options, label) {
    return withRetry(() => request(url, options, label))
}

// Product suites run from their product dir, so a selector path may be repo- or
// product-relative — suffix-match the tracked index (full even under sparse checkout).
export function trackedTestPaths(runGit = execFileSync) {
    // The tracked-file list is a few MB; the 1MB execFileSync default truncates it.
    return runGit('git', ['ls-files', '*.py', '*.js', '*.jsx', '*.ts', '*.tsx'], {
        encoding: 'utf8',
        maxBuffer: 64 * 1024 * 1024,
    })
        .split('\n')
        .filter(Boolean)
}

export function repoPathResolver(trackedPaths = trackedTestPaths()) {
    const trackedSet = new Set(trackedPaths)
    const bySuffix = new Map()
    for (const path of trackedPaths) {
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
        return (bySuffix.get(selectorPath.split('/').pop()) || []).filter((p) => p.endsWith(`/${selectorPath}`))
    }
}

// Ambiguous suffix matches only count when every candidate agrees on the owner.
// `slack` is the owning team's notifications channel, only set when the owner is unambiguous.
export function resolveOwners(items, toRepoPaths = repoPathResolver(), producer = null) {
    const candidates = new Map()
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
            const producerArgs = producer ? ['--producer', producer] : []
            const out = execFileSync('python3', ['-m', 'owners_yaml', '--purpose', 'notifications', ...producerArgs], {
                encoding: 'utf8',
                input: allPaths.join('\n'),
                env: { ...process.env, PYTHONPATH: 'packages/owners-yaml' },
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
        const slack = owner === 'unowned' ? null : (resolved[paths[0]]?.slack ?? null)
        return { owner, repoPath: paths.length === 1 ? paths[0] : null, slack }
    }
}

export function cell(text) {
    return { type: 'raw_text', text }
}

export function linkedCell(links) {
    const elements = links.flatMap(({ url, text }, index) => [
        ...(index > 0 ? [{ type: 'text', text: ' ' }] : []),
        { type: 'link', url, text },
    ])
    return { type: 'rich_text', elements: [{ type: 'rich_text_section', elements }] }
}

export function shortName(selector) {
    const name = selector.split('::').pop()
    return name.length > 36 ? `${name.slice(0, 35)}…` : name
}

// Goals every report shares: one table, one footer link back to the workflow that posts it.
export function editWorkflowBlock() {
    const workflowPath = GITHUB_WORKFLOW_REF.split('@')[0].replace(`${GITHUB_REPOSITORY}/`, '')
    if (!GITHUB_REPOSITORY || !workflowPath) {
        return null
    }
    const editUrl = `${GITHUB_SERVER_URL}/${GITHUB_REPOSITORY}/edit/${GITHUB_REF_NAME}/${workflowPath}`
    return { type: 'context', elements: [{ type: 'mrkdwn', text: `<${editUrl}|edit this workflow>` }] }
}

export async function postToSlack(blocks, text, { threadTs, channel = SLACK_CHANNEL } = {}) {
    const res = await fetch('https://slack.com/api/chat.postMessage', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json; charset=utf-8', Authorization: `Bearer ${SLACK_BOT_TOKEN}` },
        body: JSON.stringify({
            channel,
            blocks,
            text, // notification fallback
            unfurl_links: false,
            thread_ts: threadTs || undefined,
        }),
    })
    const data = await res.json()
    if (!data.ok) {
        const validationDetails = Array.isArray(data.response_metadata?.messages)
            ? `: ${data.response_metadata.messages.join('; ')}`
            : ''
        throw new Error(`Slack chat.postMessage failed: ${data.error}${validationDetails}`)
    }
    // `channel` is the resolved channel ID, which chat.getPermalink needs when the post was addressed by name.
    return { ts: data.ts, channel: data.channel }
}

export async function slackPermalink({ channel, ts }) {
    const url = new URL('https://slack.com/api/chat.getPermalink')
    url.searchParams.set('channel', channel)
    url.searchParams.set('message_ts', ts)
    const res = await fetch(url, { headers: { Authorization: `Bearer ${SLACK_BOT_TOKEN}` } })
    const data = await res.json()
    if (!data.ok) {
        throw new Error(`Slack chat.getPermalink failed: ${data.error}`)
    }
    return data.permalink
}

export const teamLabel = (owner) => owner.replace(/^team-/, '')

// The per-team slices carry the same rows as the channel digest. Takes [{owner, slack, row}]
// and groups by owner.
export function buildTeamDigests(entries) {
    const byOwner = new Map()
    for (const { owner, slack, row } of entries) {
        if (owner === 'unowned' || !slack) {
            continue
        }
        if (!byOwner.has(owner)) {
            byOwner.set(owner, { owner, channel: slack, rows: [] })
        }
        byOwner.get(owner).rows.push(row)
    }
    return [...byOwner.values()].sort((a, b) => b.rows.length - a.rows.length)
}

function buildTeamIndexBlocks(posted, rowLabel) {
    return [
        {
            type: 'table',
            column_settings: [{ align: 'left' }, { align: 'right' }, { align: 'left' }],
            rows: [
                [cell('team'), cell(rowLabel), cell('post')],
                ...posted.map(({ owner, channel, rows, url }) => [
                    cell(teamLabel(owner)),
                    cell(String(rows.length)),
                    url ? linkedCell([{ url, text: channel }]) : cell(channel),
                ]),
            ],
        },
    ]
}

const SLACK = {
    post: postToSlack,
    permalink: slackPermalink,
    // chat.postMessage allows about one message per second per channel.
    pause: () => new Promise((resolve) => setTimeout(resolve, 1100)),
}

async function postToTeamChannel(team, { report, digestUrl, slack }) {
    try {
        const post = await slack.post(report.teamBlocks(team, digestUrl), report.title, { channel: team.channel })
        return { ...team, url: await slack.permalink(post).catch(() => null) }
    } catch (err) {
        console.warn(`team digest for ${team.owner} failed: ${err.message}`)
        return null
    }
}

// Sends each team its slice, then indexes those posts in the digest thread. A slice that cannot
// go to its channel stays in the thread, so no team's rows are lost. `withheld` names a reason to
// keep every slice in the thread. A team whose channel is `digestChannel` keeps its slice in the
// thread too, so that channel does not get the digest twice. `report` supplies the report's
// `title`, the `rowLabel` for the index, and its `teamBlocks(team, digestUrl)` and
// `threadSliceBlocks(team, reason)` builders.
export async function deliverTeamDigests(
    teamDigests,
    { digest, report, withheld = null, digestChannel = SLACK_CHANNEL, slack = SLACK }
) {
    const digestUrl = withheld ? null : await slack.permalink(digest).catch(() => null)
    const posted = []
    for (const [index, team] of teamDigests.entries()) {
        if (index > 0) {
            await slack.pause()
        }
        const kept = withheld || (team.channel === digestChannel ? 'report already in' : null)
        const sent = kept ? null : await postToTeamChannel(team, { report, digestUrl, slack })
        if (sent) {
            posted.push(sent)
            continue
        }
        // A failed slice must not sink the slices behind it; the digest itself already landed.
        try {
            await slack.post(
                report.threadSliceBlocks(team, kept || 'not delivered to'),
                `${report.title}: ${teamLabel(team.owner)}`,
                { threadTs: digest.ts }
            )
        } catch (err) {
            console.warn(`thread slice for ${team.owner} failed: ${err.message}`)
        }
    }
    if (posted.length > 0) {
        // The team posts already landed. A failed run would invite a re-dispatch that repeats them.
        try {
            await slack.post(buildTeamIndexBlocks(posted, report.rowLabel), `${report.title}: team posts`, {
                threadTs: digest.ts,
            })
        } catch (err) {
            console.warn(`team post index failed: ${err.message}`)
        }
    }
    return posted
}
