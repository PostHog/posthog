// Weekly engineering-analytics CI digest, posted to #alerts-devex on Monday.
//
// PULL model: this script reads the engineering_analytics product's repo_overview
// endpoint (the same curated layer that backs its MCP tools and UI) ONCE for the
// last 7 complete UTC days — every headline ships with its equal-length previous-window twin,
// so one call carries the whole week-over-week table — and relays it to Slack. It
// asks for headlines only (include_series=false; the chart series exist for the
// UI) and does NOT re-derive any metric from the GitHub API — the product owns
// the numbers, this owns the cadence + the Slack relay.
//
//   GHA cron ──> GET /api/projects/:id/engineering_analytics/repo_overview/ ──> Slack
//
// One native-table message (Block Kit `table`), one row per metric, each with its WoW delta:
//   - CI minutes: billable (self-hosted) compute minutes across the whole bill,
//     master and scheduled runs included.
//   - └ merge queue: the slice of CI minutes spent on merge-queue batch branches
//     (trunk-merge/**) — broken out so queue-settings changes get their own delta.
//   - └ Depot CI: the slice of CI minutes that ran on the Depot CI engine. Depot does not count
//     these against the contract's GitHub Actions minutes, so a move to Depot CI lowers the
//     contract rows below without lowering this one.
//   - min / merged PR: the same bill divided by the week's merged-PR count (bots
//     included — the merge population that triggered the spend).
//   - est. Depot $: the product's tier-laddered estimate of that spend.
//   - ready→merge median: time from ready-for-review to merge, bots/drafts excluded
//     upstream. Falls back to the coarse open→merge median (draft + ready fused, and
//     labelled as such) when the draft/ready transitions aren't synced.
//   - re-run cycles: runs with run_attempt > 1 — the waste driver behind minutes.
//   - Depot runner min, all repos: the minutes Depot billed for GitHub Actions jobs in the whole
//     organization, read from Depot's usage API. Depot counts these against the contract. Depot CI
//     minutes are not part of that count. A sentence under the table says when the contract
//     minutes run out at the reported week's rate. Both are left out when the API cannot be read.
//
// Data caveat: the runs/jobs warehouse tables are webhook-fed and do not backfill
// a missed window, so a webhook outage undercounts the count-based rows (minutes,
// $, re-runs) and the WoW delta absorbs the hole. The PR-snapshot rows (merge
// count, cycle-time median) are robust to gaps.

import { pathToFileURL } from 'node:url'

const HOST = (process.env.POSTHOG_HOST || 'https://us.posthog.com').replace(/\/$/, '')
const PROJECT_ID = process.env.POSTHOG_PROJECT_ID || ''
const API_KEY = process.env.POSTHOG_API_KEY || ''
// Pin the source when the project has more than one connected GitHub source; otherwise
// the endpoints default to the oldest, which may not be the repo you mean.
const SOURCE_ID = process.env.ENG_ANALYTICS_SOURCE_ID || ''
const SLACK_BOT_TOKEN = process.env.SLACK_BOT_TOKEN || ''
const SLACK_CHANNEL = process.env.SLACK_CHANNEL || 'C0AS64N6DJL' // #alerts-devex
const DRY_RUN = ['1', 'true', 'yes'].includes((process.env.DRY_RUN || '').toLowerCase())

const GITHUB_SERVER_URL = process.env.GITHUB_SERVER_URL || 'https://github.com'
const GITHUB_REPOSITORY = process.env.GITHUB_REPOSITORY || ''
// 'owner/repo/.github/workflows/x.yml@refs/heads/master' — set by Actions on every run,
// so the digest's self-link survives a rename of this workflow file.
const GITHUB_WORKFLOW_REF = process.env.GITHUB_WORKFLOW_REF || ''
const GITHUB_REF_NAME = process.env.GITHUB_REF_NAME || 'master'

// The Depot contract terms come from repository variables, so a renewal needs no code change.
const DEPOT_TOKEN = process.env.DEPOT_TOKEN || ''
const DEPOT_CONTRACT_MINUTES = Number(process.env.DEPOT_CONTRACT_MINUTES || 0)
const DEPOT_CONTRACT_START = process.env.DEPOT_CONTRACT_START || ''
const DEPOT_CONTRACT_END = process.env.DEPOT_CONTRACT_END || ''

const DAY_MS = 24 * 60 * 60 * 1000
const WEEK_MS = 7 * DAY_MS

// Minutes Depot billed for GitHub Actions jobs in every repository of the organization. Depot counts
// these minutes against the contract, and its billing page shows their sum from the contract start.
async function depotBilledMinutes(startAt, endAt) {
    const res = await fetch('https://api.depot.dev/depot.core.v1.UsageService/GetUsage', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'Connect-Protocol-Version': '1',
            Authorization: `Bearer ${DEPOT_TOKEN}`,
        },
        body: JSON.stringify({ startAt: startAt.toISOString(), endAt: endAt.toISOString() }),
        signal: AbortSignal.timeout(60_000),
    })
    if (!res.ok) {
        // The response body stays out of the message, because the message goes to the public Actions log.
        throw new Error(`Depot GetUsage -> ${res.status}`)
    }
    const usage = await res.json()
    // Protobuf JSON omits empty repeated fields.
    const jobs = usage?.githubActionsJobs ?? []
    if (!usage || typeof usage !== 'object' || Array.isArray(usage) || !Array.isArray(jobs)) {
        throw new Error('Depot GetUsage returned invalid usage')
    }
    return jobs.reduce((sum, repo) => {
        // Protobuf JSON omits scalar fields at their zero default.
        const minutes = repo?.total?.minutesBilled ?? 0
        if (!repo?.total || !Number.isFinite(minutes) || minutes < 0 || !Number.isFinite(sum + minutes)) {
            throw new Error('Depot GetUsage returned invalid billed minutes')
        }
        return sum + minutes
    }, 0)
}

// Contract usage through the end of the reported week, or null when it cannot be read. The digest
// still posts without it, because the CI table does not depend on Depot's API.
async function depotContractUsage(weekStart, weekEnd) {
    const contractStart = new Date(`${DEPOT_CONTRACT_START}T00:00:00Z`)
    const contractEnd = new Date(`${DEPOT_CONTRACT_END}T00:00:00Z`)
    if (
        !DEPOT_TOKEN ||
        !Number.isFinite(DEPOT_CONTRACT_MINUTES) ||
        DEPOT_CONTRACT_MINUTES <= 0 ||
        !Number.isFinite(contractStart.getTime()) ||
        !Number.isFinite(contractEnd.getTime()) ||
        isoDay(contractStart) !== DEPOT_CONTRACT_START ||
        isoDay(contractEnd) !== DEPOT_CONTRACT_END ||
        contractStart >= weekEnd ||
        contractEnd <= weekEnd
    ) {
        console.warn('Depot token or active contract terms missing or invalid. Skipping the contract rows.')
        return null
    }
    try {
        const [used, lastWeek, priorWeek] = await Promise.all([
            depotBilledMinutes(contractStart, weekEnd),
            depotBilledMinutes(weekStart, weekEnd),
            depotBilledMinutes(new Date(weekStart.getTime() - WEEK_MS), weekStart),
        ])
        return { used, lastWeek, priorWeek, contractEnd }
    } catch {
        // Fetch and parse errors can include response data in the public Actions log.
        console.warn('Depot usage unavailable. Skipping the contract rows.')
        return null
    }
}

function isoDay(date) {
    return date.toISOString().slice(0, 10)
}

function contractSummary(contract, weekEnd) {
    const used = `Depot contract: ${fmtMinutes(contract.used)} of ${fmtMinutes(DEPOT_CONTRACT_MINUTES)} GitHub Actions minutes used through ${isoDay(new Date(weekEnd.getTime() - DAY_MS))}. Depot CI minutes are not counted here.`
    const remaining = DEPOT_CONTRACT_MINUTES - contract.used
    if (remaining <= 0) {
        return `${used} The contract minutes are used up.`
    }
    if (!(contract.lastWeek > 0)) {
        return used
    }
    const remainingDays = remaining / (contract.lastWeek / 7)
    const daysLeft = (contract.contractEnd.getTime() - weekEnd.getTime()) / DAY_MS
    const contractEnd = isoDay(contract.contractEnd)
    const daysShort = Math.round(daysLeft - remainingDays)
    if (daysShort <= 0) {
        return `${used} At last week's rate they last until the contract ends on ${contractEnd}.`
    }
    const runOut = new Date(weekEnd.getTime() + remainingDays * DAY_MS)
    return `${used} At last week's rate they run out around ${isoDay(runOut)}, ${daysShort} days before the contract ends on ${contractEnd}.`
}

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
    // Bounds every attempt (the gateway answers within ~2min; this only catches a hung connection)
    // so worst-case retries stay well inside the workflow's timeout-minutes.
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
        // A non-JSON body (proxy interstitial, maintenance HTML) is still a failure whatever the
        // status — the endpoint only speaks JSON — but it's infra noise, so always worth retrying.
        fail(`non-JSON response (${body.slice(0, 120)})`, true)
    }
    if (!res.ok) {
        // The endpoint 400s with a clear `detail` when no GitHub source is connected — a
        // configuration error a retry can't fix; 5xx/429 are transients worth riding out.
        fail(parsed?.detail || body, res.status >= 500 || res.status === 429)
    }
    return parsed
}

const RETRY_ATTEMPTS = 3
const RETRY_DELAY_MS = 30_000

// The warehouse queries share a ClickHouse cluster with everything else; a contended Monday
// morning can push one attempt past the API gateway's timeout. Ride transients out instead of
// failing the week's digest. Errors without a retryable flag (network failures, aborts) retry too.
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

function fmtInt(n) {
    return Math.round(n).toLocaleString('en-US')
}

// Minutes at CI-bill scale: M-notation from 100k up ('3.04M', '0.38M'), thousands-separated
// below. The low threshold keeps same-unit rows — CI minutes and its merge-queue slice — in one
// notation, while a near-zero slice still reads as a plain count instead of '0.00M'.
function fmtMinutes(minutes) {
    return minutes >= 100_000 ? `${(minutes / 1_000_000).toFixed(2)}M` : fmtInt(minutes)
}

// Estimated dollars, no cents ('$13,160').
function fmtUsd(amount) {
    return `$${fmtInt(amount)}`
}

// PR-lifecycle durations: seconds → '3d4h' / '7h55m' / '42m'.
function fmtLongDuration(seconds) {
    const totalMinutes = Math.round(seconds / 60)
    const d = Math.floor(totalMinutes / 1440)
    const h = Math.floor((totalMinutes % 1440) / 60)
    const m = totalMinutes % 60
    if (d > 0) {
        return h === 0 ? `${d}d` : `${d}d${h}h`
    }
    if (h > 0) {
        return m === 0 ? `${h}h` : `${h}h${String(m).padStart(2, '0')}m`
    }
    return `${m}m`
}

// Signed one-decimal WoW delta: '+66.5%' / '-1.0%'. '+0.0%' covers the -0.0 rounding edge.
// A zero prior-week baseline (e.g. a clean week with no re-run cycles) has no finite
// percent, so 0->positive shows '+∞%' and 0->0 stays '+0.0%'.
function fmtDelta(current, previous) {
    if (previous === 0) {
        return current === 0 ? '+0.0%' : '+∞%'
    }
    const pct = ((current - previous) / previous) * 100
    let s = pct.toFixed(1)
    if (s === '-0.0') {
        s = '0.0'
    }
    return s.startsWith('-') ? `${s}%` : `+${s}%`
}

function cell(text) {
    return { type: 'raw_text', text }
}

function metricRow(metric, curValue, prevValue, format) {
    return [cell(metric), cell(format(curValue)), cell(format(prevValue)), cell(fmtDelta(curValue, prevValue))]
}

// One table row per metric, added only when both windows carry the value, so a
// not-yet-synced jobs source (null cost fields) or an old backend (no merged_pr_count)
// degrades to fewer rows instead of a broken message.
function tableRows(overview) {
    const rows = []
    const add = (metric, curValue, prevValue, format) => {
        if (curValue == null || prevValue == null) {
            return
        }
        rows.push(metricRow(metric, curValue, prevValue, format))
    }
    // Null-propagating so `add`'s missing-value guard stays the only degradation path.
    const perPr = (minutes, merges) => (minutes != null && merges ? minutes / merges : null)
    add('CI minutes', overview.billable_minutes, overview.billable_minutes_prev, fmtMinutes)
    add('└ merge queue', overview.merge_queue_billable_minutes, overview.merge_queue_billable_minutes_prev, fmtMinutes)
    add('└ Depot CI', overview.depot_ci_billable_minutes, overview.depot_ci_billable_minutes_prev, fmtMinutes)
    add(
        'min / merged PR',
        perPr(overview.billable_minutes, overview.merged_pr_count),
        perPr(overview.billable_minutes_prev, overview.merged_pr_count_prev),
        fmtInt
    )
    add('est. Depot $', overview.estimated_cost_usd, overview.estimated_cost_usd_prev, fmtUsd)
    // Cycle time reads ready→merge, which excludes time spent as a draft. Both windows have to carry
    // it to compare like with like, so a repo without the issue-events sync (or a week that straddles
    // its first sync) falls back to the coarse open→merge median, labelled as what it is.
    const [cycleMetric, cycleCur, cyclePrev] =
        overview.median_ready_to_merge_seconds != null && overview.median_ready_to_merge_seconds_prev != null
            ? [
                  'ready→merge median',
                  overview.median_ready_to_merge_seconds,
                  overview.median_ready_to_merge_seconds_prev,
              ]
            : ['open→merge median', overview.median_open_to_merge_seconds, overview.median_open_to_merge_seconds_prev]
    add(cycleMetric, cycleCur, cyclePrev, fmtLongDuration)
    add('re-run cycles', overview.rerun_cycles, overview.rerun_cycles_prev, fmtInt)
    return rows
}

// Actions logs are public, so dry runs use placeholders for Depot's billing data.
function depotDigest(contract, weekEnd) {
    const metric = 'Depot runner min, all repos'
    if (DRY_RUN) {
        return {
            row: [cell(metric), ...Array(3).fill(cell('hidden in dry runs'))],
            summary: 'Depot contract line hidden in dry runs.',
        }
    }
    return {
        row: metricRow(metric, contract.lastWeek, contract.priorWeek, fmtMinutes),
        summary: contractSummary(contract, weekEnd),
    }
}

function buildBlocks(weekStart, weekEnd, rows, depotSummary) {
    const lastDay = new Date(weekEnd.getTime() - DAY_MS)
    const blocks = [
        {
            type: 'section',
            text: {
                type: 'mrkdwn',
                text: `*Weekly CI, ${isoDay(weekStart)} to ${isoDay(lastDay)} UTC* _(vs prior week)_`,
            },
        },
        {
            type: 'table',
            column_settings: [{ align: 'left' }, { align: 'right' }, { align: 'right' }, { align: 'right' }],
            rows: [[cell('metric'), cell('last week'), cell('prior week'), cell('Δ')], ...rows],
        },
    ]
    if (depotSummary) {
        blocks.push({ type: 'section', text: { type: 'mrkdwn', text: depotSummary } })
    }
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
            text: 'Weekly CI digest', // notification fallback
            unfurl_links: false,
        }),
    })
    const data = await res.json()
    if (!data.ok) {
        throw new Error(`Slack chat.postMessage failed: ${data.error}`)
    }
}

export async function main() {
    if (!PROJECT_ID || !API_KEY) {
        // No-op (don't fail the scheduled run) until the project + read key are wired.
        console.warn('POSTHOG_PROJECT_ID / POSTHOG_API_KEY not set — skipping digest. Wire them to enable.')
        return
    }
    // The window ends at the last UTC midnight instead of at run time. The Depot job-attempts table
    // syncs on a schedule and a job that is still running has no duration, so a window that ends at
    // run time under-counts its last hours. Whole UTC days also match the days on Depot's usage page,
    // which lets a reader reconcile the minutes against it.
    const weekEnd = new Date()
    weekEnd.setUTCHours(0, 0, 0, 0)
    const weekStart = new Date(weekEnd.getTime() - WEEK_MS)
    // One headline-only call: the endpoint bakes every metric's equal-length previous-window
    // twin (prev = [date_from - 7d, date_from)) and the merged-PR counts into the same scans,
    // so the rows share windows exactly without a second call.
    const overview = await apiWithRetry('repo_overview', {
        date_from: weekStart.toISOString(),
        date_to: weekEnd.toISOString(),
        include_series: 'false',
    })
    const rows = tableRows(overview)
    if (rows.length === 0) {
        // Every metric was null (key valid but nothing synced). Fail the job so the
        // breakage is visible instead of posting an empty table.
        throw new Error('repo_overview returned no usable metrics — not posting. Check the connected source.')
    }
    const contract = await depotContractUsage(weekStart, weekEnd)
    const depot = contract && depotDigest(contract, weekEnd)
    if (depot) {
        rows.push(depot.row)
    }
    const blocks = buildBlocks(weekStart, weekEnd, rows, depot?.summary)
    if (DRY_RUN) {
        console.info(JSON.stringify(blocks, null, 2))
        return
    }
    if (!SLACK_BOT_TOKEN) {
        // Distinct from dry-run: a real run with no token is a misconfiguration, not a success.
        throw new Error('SLACK_BOT_TOKEN not set on a non-dry run — refusing to silently skip.')
    }
    await postToSlack(blocks)
    console.info(`Posted weekly CI digest to ${SLACK_CHANNEL}.`)
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
    main().catch((err) => {
        console.error(err)
        process.exit(1)
    })
}
