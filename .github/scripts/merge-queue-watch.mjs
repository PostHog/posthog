// Merge queue loop watcher. It only reads from Trunk, and posts to Slack only when
// SLACK_BOT_TOKEN and SLACK_CHANNEL are set and --dry is absent.
//   node merge-queue-watch.mjs --dry [--at 2026-10-21T22:40:00Z]
//
// Three rules read one fetch of the last WINDOW_MINUTES of Trunk test runs:
// - short window: a PR in >= PR_SHORT_THRESHOLD failed runs in the last SHORT_WINDOW_MINUTES.
// - long window: a PR in >= PR_LONG_THRESHOLD failed runs in the last WINDOW_MINUTES.
// - cycles: an unmerged PR that passed when Trunk tested it alone and then failed again in a later
//   batch at least CYCLE_THRESHOLD times. Only PRs with enough failed runs get their timeline read.
// A fourth signal fires on the overall failure rate. The thresholds are untuned starting values.
//
// A PR batched with the real culprit fails in the same runs, so the count rules can name a victim.
// A culprit that passes when tested alone never gets isolated by the count rules, which is what the
// cycle rule is for. The labels below say which case each PR looks like.

import { pathToFileURL } from 'node:url'

const TRUNK_API = 'https://api.trunk.io/v1'
const REPO = { host: 'github.com', owner: 'PostHog', name: 'posthog' }
const BRANCH = 'master'
const WINDOW_MINUTES = 180
const SHORT_WINDOW_MINUTES = 60
const PR_SHORT_THRESHOLD = 4
const PR_LONG_THRESHOLD = 6
const CYCLE_THRESHOLD = 2
// A PR needs this many failed runs in the long window before its timeline is read. This gates the
// timeline calls, and it stops a PR with two unlucky flakes from reading as a cycle.
const CYCLE_MIN_FAILED_RUNS = 4
const FAILED_RUNS_PER_30M_THRESHOLD = 10
const TIMELINE_CONCURRENCY = 5
// Timeline reads are enrichment, so they get a total budget well under the workflow's five minute limit.
const TIMELINE_BUDGET_MS = 60000
const TIMELINE_TIMEOUT_MS = 10000
// A new alert inside the cooldown needs one of these labels on a PR that no recent alert named.
const ESCALATION_LABELS = ['hidden', 'likely']
// A repeat alert for the same labeled PR inside this window stays quiet.
const COOLDOWN_MINUTES = 120
const ALERT_EVENT_TYPE = 'merge_queue_loop_alert'
const PAGE_SIZE = 100 // Trunk rejects take > 100
// Slack rejects a section longer than 3000 characters, so the metrics line stays well under that.
const MAX_METRIC_SERIES = 6
const MAX_FINDINGS_SHOWN = 8
const ALERT_OPENED_EVENT = 'merge_queue_loop_opened'
const WEBHOOK_ATTEMPTS = 3
const WEBHOOK_RETRY_DELAY_MS = 2000
const WEBHOOK_TIMEOUT_MS = 10000

export const LABELS = {
    hidden: 'culprit hidden by bisection',
    likely: 'likely culprit, fails alone',
    recent: 'repeated in the last hour',
    victim: 'possible victim',
}
// Most useful first, so the alert leads with the PR a person should look at.
const LABEL_ORDER = ['hidden', 'likely', 'recent', 'victim']

const MINUTE = 60 * 1000
const defaultSleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))
let trunkCalls = 0

function trunkToken() {
    if (!process.env.TRUNK_API_TOKEN) {
        throw new Error('TRUNK_API_TOKEN is not set')
    }
    return process.env.TRUNK_API_TOKEN
}

async function trunk(path, body, timeoutMs = 30000) {
    trunkCalls++
    const res = await fetch(`${TRUNK_API}${path}`, {
        method: body ? 'POST' : 'GET',
        headers: { 'x-api-token': trunkToken(), 'Content-Type': 'application/json' },
        body: body ? JSON.stringify(body) : undefined,
        signal: AbortSignal.timeout(timeoutMs),
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

async function fetchTimeline(pr) {
    const res = await trunk(
        '/getSubmittedPullRequest',
        { repo: REPO, targetBranch: BRANCH, pr: { number: pr }, includeTimeline: true },
        TIMELINE_TIMEOUT_MS
    )
    return res.timeline ?? []
}

// A timeline outage must not stop the alert. A failed read drops that PR's cycles, and the whole
// step stops starting new reads once the budget is spent.
export async function fetchTimelines(prs, now = Date.now) {
    const deadline = now() + TIMELINE_BUDGET_MS
    const timelines = new Map()
    for (let i = 0; i < prs.length; i += TIMELINE_CONCURRENCY) {
        if (now() > deadline) {
            console.warn(`timeline budget spent, skipped ${prs.length - i} PRs`)
            break
        }
        await Promise.all(
            prs.slice(i, i + TIMELINE_CONCURRENCY).map(async (pr) => {
                try {
                    timelines.set(pr, await fetchTimeline(pr))
                } catch (err) {
                    console.warn(`timeline unavailable for #${pr}: ${err.message}`)
                }
            })
        )
    }
    return timelines
}

// Pure: rows -> counts. One row per (PR, test run).
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
    const endMs = until.getTime()
    const failed = [...runs.values()].filter((r) => r.outcome === 'failed')
    const countIn = (minutes) => {
        const counts = new Map()
        for (const run of failed) {
            const t = run.endedAt.getTime()
            if (t > endMs || t <= endMs - minutes * MINUTE) {
                continue
            }
            for (const pr of run.prs) {
                counts.set(pr, (counts.get(pr) ?? 0) + 1)
            }
        }
        return counts
    }
    const short = countIn(SHORT_WINDOW_MINUTES)
    const long = countIn(WINDOW_MINUTES)
    // Failed runs that held a single PR, which is the only direct evidence that a PR fails alone.
    const solo = new Map()
    for (const run of failed) {
        const t = run.endedAt.getTime()
        if (run.prs.size === 1 && t <= endMs && t > endMs - WINDOW_MINUTES * MINUTE) {
            const [pr] = run.prs
            solo.set(pr, (solo.get(pr) ?? 0) + 1)
        }
    }
    const sorted = [...long.entries()].sort((a, b) => b[1] - a[1])
    const failedLast30m = failed.filter((r) => r.endedAt.getTime() >= endMs - 30 * MINUTE).length
    return {
        short,
        long,
        solo,
        top: sorted.slice(0, 5),
        cycleCandidates: sorted.filter(([, n]) => n >= CYCLE_MIN_FAILED_RUNS).map(([pr]) => pr),
        failedRuns: failed.length,
        totalRuns: runs.size,
        failedLast30m,
        rateFires: failedLast30m >= FAILED_RUNS_PER_30M_THRESHOLD,
    }
}

// Pure: one PR's timeline -> whether it has merged and how many cycles it ran in the long window.
// A cycle is a pass when Trunk tested the PR alone, then a later failure in a batch of several PRs.
export function analyzeTimeline(timeline, until) {
    const endMs = until.getTime()
    const events = timeline
        .map((e) => ({ ...e, at: new Date(e.timestamp).getTime() }))
        .filter((e) => e.at <= endMs)
        .sort((a, b) => a.at - b.at)
    if (events.some((e) => e.state === 'merged')) {
        return { merged: true, cycles: 0 }
    }
    // Each pass waits for the next batch failure, and a failure closes at most one pass, so two passes
    // before one failure make one cycle.
    let cycles = 0
    let awaitingFailure = false
    for (const e of events.filter((e) => e.at > endMs - WINDOW_MINUTES * MINUTE)) {
        if (e.state === 'pending' && e.pending?.reason === 'bisection_test_run_passed') {
            awaitingFailure = true
        } else if (
            awaitingFailure &&
            e.state === 'pending_failure' &&
            (e.testRun?.testedPullRequests ?? []).length > 1
        ) {
            cycles++
            awaitingFailure = false
        }
    }
    return { merged: false, cycles }
}

// Pure: counts and cycles -> labeled PRs, most useful first. "Fails alone" needs a failed run that
// held only that PR. Batch failures alone leave a PR a possible victim.
export function classify(counts, cyclesByPr) {
    const prs = new Set()
    for (const [pr, n] of counts.short) {
        if (n >= PR_SHORT_THRESHOLD) {
            prs.add(pr)
        }
    }
    for (const [pr, n] of counts.long) {
        if (n >= PR_LONG_THRESHOLD) {
            prs.add(pr)
        }
    }
    for (const [pr, cycles] of cyclesByPr) {
        if (cycles >= CYCLE_THRESHOLD && (counts.long.get(pr) ?? 0) >= CYCLE_MIN_FAILED_RUNS) {
            prs.add(pr)
        }
    }
    const findings = [...prs].map((pr) => {
        const failed60 = counts.short.get(pr) ?? 0
        const failed180 = counts.long.get(pr) ?? 0
        const cycles = cyclesByPr.get(pr) ?? 0
        const inShort = failed60 >= PR_SHORT_THRESHOLD
        const inLong = failed180 >= PR_LONG_THRESHOLD
        let label = 'recent'
        if (cycles >= CYCLE_THRESHOLD && failed180 >= CYCLE_MIN_FAILED_RUNS) {
            label = 'hidden'
        } else if (inShort && inLong && (counts.solo?.get(pr) ?? 0) > 0) {
            label = 'likely'
        } else if (inLong) {
            label = 'victim'
        }
        return { pr, label, failed60, failed180, cycles }
    })
    return findings.sort(
        (a, b) => LABEL_ORDER.indexOf(a.label) - LABEL_ORDER.indexOf(b.label) || b.failed180 - a.failed180
    )
}

function alertKeys(findings, rateFires) {
    const keys = findings.map((f) => `${f.label}:${f.pr}`)
    return keys.length === 0 && rateFires ? ['rate'] : keys
}

function describe(findings, verdict) {
    const lines = findings.map(
        (f) =>
            `#${f.pr}: ${LABELS[f.label]} (${f.failed60} failed runs in 60 min, ${f.failed180} in ${WINDOW_MINUTES} min, ${f.cycles} cycles)`
    )
    if (verdict.rateFires) {
        lines.push(`${verdict.failedLast30m} failed runs in the last 30 minutes`)
    }
    return lines
}

function parseMetrics(text) {
    const pick = (name) =>
        text
            .split('\n')
            .filter((l) => l.startsWith(name) && !l.includes('} 0'))
            .map((l) => l.replace(/repo=".*?",branch="master",/, ''))
    return { restarts: pick('mq_pr_restarts_1h_total') }
}

function restartSummary(series) {
    if (series.length === 0) {
        return 'unavailable or none'
    }
    const shown = series.slice(0, MAX_METRIC_SERIES).join(' ')
    return series.length > MAX_METRIC_SERIES ? `${shown} (+${series.length - MAX_METRIC_SERIES} more)` : shown
}

function slackMessage(findings, verdict, metrics, investigation) {
    const owner = process.env.ALERT_OWNER_SLACK_ID ? `<@${process.env.ALERT_OWNER_SLACK_ID}> ` : ''
    const hidden = findings.length - MAX_FINDINGS_SHOWN
    const bullets = findings
        .slice(0, MAX_FINDINGS_SHOWN)
        .map(
            (f) =>
                `• <https://github.com/PostHog/posthog/pull/${f.pr}|#${f.pr}> ${LABELS[f.label]}: ${f.failed60} failed runs in 60 min, ${f.failed180} in ${WINDOW_MINUTES} min, ${f.cycles} cycles`
        )
        .concat(hidden > 0 ? [`• +${hidden} more PRs`] : [])
        .concat(verdict.rateFires ? [`• ${verdict.failedLast30m} failed runs in the last 30 minutes`] : [])
        .join('\n')
    return {
        text: `${owner}Merge queue loop suspected: ${describe(findings.slice(0, MAX_FINDINGS_SHOWN), verdict).join('; ')}`,
        blocks: [
            {
                type: 'section',
                text: {
                    type: 'mrkdwn',
                    text:
                        `${owner}*Merge queue loop suspected* (prototype, may be wrong)\n${bullets}\n` +
                        `Failed ${verdict.failedRuns} of ${verdict.totalRuns} runs in the last ${WINDOW_MINUTES} minutes. ` +
                        `Restarts (1h): ${restartSummary(metrics.restarts)}`,
                },
            },
        ],
        metadata: {
            event_type: ALERT_EVENT_TYPE,
            event_payload: { keys: alertKeys(findings, verdict.rateFires).join('|'), investigation },
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

// Slack is the only state. Every alert inside the cooldown window, newest first. History is paged
// because a busy channel can push an alert past the first page.
async function recentAlerts(now) {
    const oldest = String((now.getTime() - COOLDOWN_MINUTES * MINUTE) / 1000)
    const alerts = []
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
        alerts.push(...(history.messages ?? []).filter((m) => m.metadata?.event_type === ALERT_EVENT_TYPE))
        cursor = history.has_more ? (history.response_metadata?.next_cursor ?? '') : ''
    } while (cursor)
    return alerts
}

// The workflow behind the webhook reads `properties.channel` and `properties.ts` to reply in the
// alert thread, so dropping either from the payload leaves the agent's answer with nowhere to land.
async function startInvestigation(url, payload, sleep) {
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
            // The URL is the only credential, and a malformed one appears in the fetch error text.
            lastError = err.message.replaceAll(url, '[webhook url]')
        }
        await sleep(WEBHOOK_RETRY_DELAY_MS * attempt)
    }
    throw new Error(`Could not start the investigation after ${WEBHOOK_ATTEMPTS} attempts: ${lastError}`)
}

function investigationPayload(findings, verdict, ts) {
    return {
        event: ALERT_OPENED_EVENT,
        distinct_id: 'merge-queue-detector',
        properties: {
            channel: process.env.SLACK_CHANNEL,
            ts,
            // Stable per alert, so the receiver can drop a repeat start for the same message.
            alert_id: `${process.env.SLACK_CHANNEL}:${ts}`,
            window_minutes: WINDOW_MINUTES,
            reasons: describe(findings.slice(0, MAX_FINDINGS_SHOWN), verdict).join('; '),
            top_prs: verdict.top.map(([pr, failed_runs]) => ({ pr, failed_runs })),
            verdicts: findings.slice(0, MAX_FINDINGS_SHOWN).map((f) => ({
                pr: f.pr,
                label: LABELS[f.label],
                failed_runs_60m: f.failed60,
                failed_runs_180m: f.failed180,
                cycles: f.cycles,
            })),
            failed_runs: verdict.failedRuns,
            total_runs: verdict.totalRuns,
            failed_last_30m: verdict.failedLast30m,
        },
    }
}

// Records on the alert message that the webhook accepted the start, so a later tick does not repeat it.
// A failed update leaves the message pending, which can repeat the start once. The `alert_id` in the
// payload lets the receiver drop that repeat, and failing the run here would not undo the start.
async function markInvestigationStarted(ts, message) {
    try {
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
    } catch (err) {
        console.warn(`could not mark the investigation as started: ${err.message}`)
    }
}

// The alert is only supplementary context, so a metrics outage must not stop the alert.
async function fetchRestartMetrics() {
    try {
        return parseMetrics(await trunk('/getMergeQueueMetrics'))
    } catch (err) {
        console.warn(`metrics unavailable: ${err.message}`)
        return { restarts: [] }
    }
}

export async function main({ argv = process.argv.slice(2), sleep = defaultSleep } = {}) {
    const dry = argv.includes('--dry')
    const atIdx = argv.indexOf('--at')
    const now = atIdx >= 0 ? new Date(argv[atIdx + 1]) : new Date()
    const since = new Date(now.getTime() - WINDOW_MINUTES * MINUTE)

    const rows = await fetchResults(since, now)
    const verdict = evaluate(rows, now)
    const timelines = await fetchTimelines(verdict.cycleCandidates)
    const cyclesByPr = new Map()
    const merged = new Set()
    for (const [pr, timeline] of timelines) {
        const result = analyzeTimeline(timeline, now)
        if (result.merged) {
            merged.add(pr)
        } else {
            cyclesByPr.set(pr, result.cycles)
        }
    }
    // A PR that merged is out of the queue, so the count rules skip it too.
    const unmerged = (counts) => new Map([...counts].filter(([pr]) => !merged.has(pr)))
    const findings = classify(
        { short: unmerged(verdict.short), long: unmerged(verdict.long), solo: unmerged(verdict.solo) },
        cyclesByPr
    )
    console.log(
        JSON.stringify(
            {
                at: now.toISOString(),
                trunkCalls,
                fire: findings.length > 0 || verdict.rateFires,
                findings,
                rateFires: verdict.rateFires,
                failedRuns: verdict.failedRuns,
                totalRuns: verdict.totalRuns,
                failedLast30m: verdict.failedLast30m,
                cycleCandidates: verdict.cycleCandidates.length,
            },
            null,
            1
        )
    )
    if (findings.length === 0 && !verdict.rateFires) {
        return
    }
    const webhook = process.env.INVESTIGATION_WEBHOOK_URL
    const metrics = await fetchRestartMetrics()
    const message = slackMessage(findings, verdict, metrics, webhook ? 'pending' : 'off')
    if (dry || !process.env.SLACK_BOT_TOKEN || !process.env.SLACK_CHANNEL) {
        console.log('would post:\n' + message.blocks[0].text.text)
        return
    }
    const keys = alertKeys(findings, verdict.rateFires)
    const recent = await recentAlerts(now)
    const keysOf = (m) => (m.metadata.event_payload?.keys ?? '').split('|')
    const alerted = new Set(recent.flatMap(keysOf))
    // Inside the cooldown, only a culprit label on a PR that no recent alert named breaks the quiet
    // period. A new victim or the rate signal alone stays quiet, so a long spike does not alert every tick.
    const escalates = keys.some((k) => !alerted.has(k) && ESCALATION_LABELS.some((label) => k.startsWith(`${label}:`)))
    if (recent.length > 0 && !escalates) {
        // The alert posted but its webhook failed on an earlier tick. Retry on that alert's thread, and
        // only for an alert that names one of the PRs flagged now.
        const pending = recent.find(
            (m) =>
                webhook &&
                m.metadata.event_payload?.investigation === 'pending' &&
                keysOf(m).some((k) => keys.includes(k))
        )
        if (pending) {
            await startInvestigation(webhook, investigationPayload(findings, verdict, pending.ts), sleep)
            await markInvestigationStarted(pending.ts, {
                text: pending.text,
                blocks: pending.blocks,
                metadata: pending.metadata,
            })
            return
        }
        console.log('cooldown: a recent alert covers this, and no new culprit label appeared')
        return
    }
    const posted = await slack('chat.postMessage', {
        channel: process.env.SLACK_CHANNEL,
        unfurl_links: false,
        ...message,
    })
    if (webhook) {
        await startInvestigation(webhook, investigationPayload(findings, verdict, posted.ts), sleep)
        await markInvestigationStarted(posted.ts, message)
    }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
    main().catch((e) => {
        console.error(e)
        process.exit(1)
    })
}
