// Merge queue loop watcher. It only reads from Trunk, and posts to Slack only when
// SLACK_BOT_TOKEN and SLACK_CHANNEL are set and --dry is absent.
//   node merge-queue-watch.mjs --dry [--at 2026-10-21T22:40:00Z]
//
// Fires when one PR sits in >= PR_FAILED_RUNS_THRESHOLD failed test runs inside the window, or when
// failed runs per half hour reach FAILED_RUNS_PER_30M_THRESHOLD. The thresholds are untuned
// starting values. The top PR is a candidate only: PRs batched with the real culprit fail in the
// same runs, so a victim can tie with it or lead.

import { readFileSync } from 'node:fs'
import { homedir } from 'node:os'

const TRUNK_API = 'https://api.trunk.io/v1'
const REPO = { host: 'github.com', owner: 'PostHog', name: 'posthog' }
const BRANCH = 'master'
const WINDOW_MINUTES = Number(process.env.WINDOW_MINUTES ?? 60)
const PR_FAILED_RUNS_THRESHOLD = 4
const FAILED_RUNS_PER_30M_THRESHOLD = 10
// A repeat alert for the same top PR inside this window stays quiet.
const COOLDOWN_MINUTES = 120
const ALERT_EVENT_TYPE = 'merge_queue_loop_alert'
const PAGE_SIZE = 100 // Trunk rejects take > 100
const ALERT_OPENED_EVENT = 'merge_queue_loop_opened'
const WEBHOOK_ATTEMPTS = 3
const WEBHOOK_RETRY_DELAY_MS = 2000
const WEBHOOK_TIMEOUT_MS = 10000

function trunkToken() {
    if (process.env.TRUNK_API_TOKEN) {
        return process.env.TRUNK_API_TOKEN
    }
    return readFileSync(`${homedir()}/.config/trunk-mq/token`, 'utf8').trim()
}

async function trunk(path, body) {
    const res = await fetch(`${TRUNK_API}${path}`, {
        method: body ? 'POST' : 'GET',
        headers: { 'x-api-token': trunkToken(), 'Content-Type': 'application/json' },
        body: body ? JSON.stringify(body) : undefined,
        signal: AbortSignal.timeout(30000),
    })
    if (!res.ok) {
        throw new Error(`Trunk ${path} -> HTTP ${res.status}`)
    }
    return path === '/getMergeQueueMetrics' ? res.text() : res.json()
}

// Newest first, paged with `offset`. An interrupted run can come back without a testRunId.
export async function fetchResults(since, until) {
    const rows = []
    for (let offset = 0; ; offset += PAGE_SIZE) {
        const page = await trunk('/listMergeQueueTestingResults', {
            repo: REPO,
            targetBranch: BRANCH,
            since: since.toISOString(),
            until: until.toISOString(),
            take: PAGE_SIZE,
            offset,
        })
        rows.push(...page.testingResults)
        if (page.testingResults.length < PAGE_SIZE || offset + PAGE_SIZE >= page.totalItems) {
            return rows
        }
    }
}

// Pure: rows -> verdict. One row per (PR, test run).
export function evaluate(rows, until) {
    const runs = new Map()
    for (const r of rows) {
        if (!r.testRunId) {
            continue
        }
        const run = runs.get(r.testRunId) ?? { outcome: r.outcome, endedAt: new Date(r.endedAt), prs: new Set() }
        run.prs.add(r.prNumber)
        runs.set(r.testRunId, run)
    }
    const failed = [...runs.values()].filter((r) => r.outcome === 'failed')
    const perPr = new Map()
    for (const run of failed) {
        for (const pr of run.prs) {
            perPr.set(pr, (perPr.get(pr) ?? 0) + 1)
        }
    }
    const top = [...perPr.entries()].sort((a, b) => b[1] - a[1]).slice(0, 5)
    const halfHourAgo = until.getTime() - 30 * 60 * 1000
    const failedLast30m = failed.filter((r) => r.endedAt.getTime() >= halfHourAgo).length
    const reasons = []
    if (top[0] && top[0][1] >= PR_FAILED_RUNS_THRESHOLD) {
        reasons.push(`#${top[0][0]} is in ${top[0][1]} failed runs in the last ${WINDOW_MINUTES} minutes`)
    }
    if (failedLast30m >= FAILED_RUNS_PER_30M_THRESHOLD) {
        reasons.push(`${failedLast30m} failed runs in the last 30 minutes`)
    }
    return { fire: reasons.length > 0, reasons, top, failedRuns: failed.length, totalRuns: runs.size, failedLast30m }
}

function parseMetrics(text) {
    const pick = (name) =>
        text
            .split('\n')
            .filter((l) => l.startsWith(name) && !l.includes('} 0') )
            .map((l) => l.replace(/repo=".*?",branch="master",/, ''))
    return {
        restarts: pick('mq_pr_restarts_1h_total'),
        depth: pick('mq_depth_current'),
    }
}

function slackMessage(verdict, metrics, investigation) {
    const owner = process.env.ALERT_OWNER_SLACK_ID ? `<@${process.env.ALERT_OWNER_SLACK_ID}> ` : ''
    const prs = verdict.top
        .map(([pr, n]) => `<https://github.com/PostHog/posthog/pull/${pr}|#${pr}> (${n} failed runs)`)
        .join(', ')
    return {
        text: `${owner}Merge queue loop suspected: ${verdict.reasons.join('; ')}`,
        blocks: [
            {
                type: 'section',
                text: {
                    type: 'mrkdwn',
                    text:
                        `${owner}*Merge queue loop suspected* (prototype, may be wrong)\n` +
                        verdict.reasons.map((r) => `• ${r}`).join('\n') +
                        `\nMost repeated PRs: ${prs}\n` +
                        `Failed ${verdict.failedRuns} of ${verdict.totalRuns} runs in the last ${WINDOW_MINUTES} minutes. ` +
                        `Restarts (1h): ${metrics.restarts.join(' ') || 'unavailable or none'}`,
                },
            },
        ],
        metadata: {
            event_type: ALERT_EVENT_TYPE,
            event_payload: { top_pr: String(verdict.top[0]?.[0] ?? ''), investigation },
        },
    }
}

async function slack(method, body) {
    const res = await fetch(`https://slack.com/api/${method}`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${process.env.SLACK_BOT_TOKEN}`, 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    })
    const json = await res.json()
    if (!json.ok) {
        throw new Error(`Slack ${method}: ${json.error}`)
    }
    return json
}

// Slack is the only state. The newest alert for the same top PR inside the cooldown window keeps this
// tick quiet. History is paged because a busy channel can push the alert past the first page.
async function findRecentAlert(topPr, now) {
    const oldest = String((now.getTime() - COOLDOWN_MINUTES * 60 * 1000) / 1000)
    let cursor = ''
    do {
        // Slack read methods take query parameters, not a JSON body.
        const params = new URLSearchParams({
            channel: process.env.SLACK_CHANNEL,
            oldest,
            limit: '100',
            include_all_metadata: 'true',
        })
        if (cursor) {
            params.set('cursor', cursor)
        }
        const res = await fetch(`https://slack.com/api/conversations.history?${params}`, {
            headers: { Authorization: `Bearer ${process.env.SLACK_BOT_TOKEN}` },
        })
        const history = await res.json()
        if (!history.ok) {
            throw new Error(`Slack conversations.history: ${history.error}`)
        }
        const found = (history.messages ?? []).find(
            (m) => m.metadata?.event_type === ALERT_EVENT_TYPE && m.metadata.event_payload?.top_pr === String(topPr)
        )
        if (found) {
            return found
        }
        cursor = history.has_more ? (history.response_metadata?.next_cursor ?? '') : ''
    } while (cursor)
    return undefined
}

// The workflow behind the webhook reads `properties.channel` and `properties.ts` to reply in the
// alert thread, so dropping either from the payload leaves the agent's answer with nowhere to land.
async function startInvestigation(url, payload) {
    let lastError = 'unknown'
    for (let attempt = 1; attempt <= WEBHOOK_ATTEMPTS; attempt++) {
        try {
            const res = await fetch(url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
                signal: AbortSignal.timeout(WEBHOOK_TIMEOUT_MS),
            })
            if (res.ok) {
                return
            }
            lastError = `HTTP ${res.status}`
        } catch (err) {
            lastError = err.message
        }
        await new Promise((r) => setTimeout(r, WEBHOOK_RETRY_DELAY_MS * attempt))
    }
    throw new Error(`Could not start the investigation after ${WEBHOOK_ATTEMPTS} attempts: ${lastError}`)
}

function investigationPayload(verdict, ts) {
    return {
        event: ALERT_OPENED_EVENT,
        distinct_id: 'merge-queue-watch',
        properties: {
            channel: process.env.SLACK_CHANNEL,
            ts,
            window_minutes: WINDOW_MINUTES,
            reasons: verdict.reasons,
            top_prs: verdict.top.map(([pr, failed_runs]) => ({ pr, failed_runs })),
            failed_runs: verdict.failedRuns,
            total_runs: verdict.totalRuns,
            failed_last_30m: verdict.failedLast30m,
        },
    }
}

// Records on the alert message that the webhook accepted the start, so a later tick does not repeat it.
async function markInvestigationStarted(ts, message) {
    await slack('chat.update', {
        channel: process.env.SLACK_CHANNEL,
        ts,
        text: message.text,
        blocks: message.blocks,
        metadata: {
            event_type: ALERT_EVENT_TYPE,
            event_payload: { ...message.metadata.event_payload, investigation: 'started' },
        },
    })
}

// The alert is only supplementary context, so a metrics outage must not stop the alert.
async function fetchRestartMetrics() {
    try {
        return parseMetrics(await trunk('/getMergeQueueMetrics'))
    } catch (err) {
        console.warn(`metrics unavailable: ${err.message}`)
        return { restarts: [], depth: [] }
    }
}

async function main() {
    const argv = process.argv.slice(2)
    const dry = argv.includes('--dry')
    const atIdx = argv.indexOf('--at')
    const now = atIdx >= 0 ? new Date(argv[atIdx + 1]) : new Date()
    const since = new Date(now.getTime() - WINDOW_MINUTES * 60 * 1000)

    const rows = await fetchResults(since, now)
    const verdict = evaluate(rows, now)
    console.log(JSON.stringify({ at: now.toISOString(), calls: 'results pages only', ...verdict }, null, 1))
    if (!verdict.fire) {
        return
    }
    const webhook = process.env.INVESTIGATION_WEBHOOK_URL
    const metrics = await fetchRestartMetrics()
    const message = slackMessage(verdict, metrics, webhook ? 'pending' : 'off')
    if (dry || !process.env.SLACK_BOT_TOKEN || !process.env.SLACK_CHANNEL) {
        console.log('would post:\n' + message.blocks[0].text.text)
        return
    }
    const recent = await findRecentAlert(verdict.top[0][0], now)
    if (recent) {
        // The alert posted but its webhook failed on an earlier tick. Retry on the same thread.
        if (webhook && recent.metadata.event_payload.investigation === 'pending') {
            await startInvestigation(webhook, investigationPayload(verdict, recent.ts))
            await markInvestigationStarted(recent.ts, { text: recent.text, blocks: recent.blocks, metadata: recent.metadata })
            return
        }
        console.log('cooldown: same top PR already alerted')
        return
    }
    const posted = await slack('chat.postMessage', { channel: process.env.SLACK_CHANNEL, unfurl_links: false, ...message })
    if (webhook) {
        await startInvestigation(webhook, investigationPayload(verdict, posted.ts))
        await markInvestigationStarted(posted.ts, message)
    }
}

if (import.meta.url === `file://${process.argv[1]}`) {
    main().catch((e) => {
        console.error(e)
        process.exit(1)
    })
}
