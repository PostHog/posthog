// Weekly engineering-analytics CI digest, posted to #alerts-devex on Monday.
//
// PULL model: this script reads the engineering_analytics product's repo_overview
// endpoint (the same curated layer that backs its MCP tools and UI) for the last
// 7 days and the 7 days before, and relays one week-over-week table to Slack. It
// does NOT re-derive any metric from the GitHub API — the product owns the
// numbers, this owns the cadence + the Slack relay.
//
//   GHA cron ──> GET /api/projects/:id/engineering_analytics/repo_overview/ ──> Slack
//
// One native-table message (Block Kit `table`), five rows, each with its WoW delta:
//   - CI minutes: billable (self-hosted) compute minutes across the whole bill,
//     master and scheduled runs included.
//   - min / merged PR: the same bill divided by the week's merged-PR count (bots
//     included — the merge population that triggered the spend).
//   - est. Depot $: the product's tier-laddered estimate of that spend.
//   - open→merge median: bots/drafts excluded upstream; coarse by design (draft +
//     ready-for-review fused).
//   - re-run cycles: runs with run_attempt > 1 — the waste driver behind minutes.
//
// Data caveat: the runs/jobs warehouse tables are webhook-fed and do not backfill
// a missed window, so a webhook outage undercounts the count-based rows (minutes,
// $, re-runs) and the WoW delta absorbs the hole. The PR-snapshot rows (merge
// count, open→merge median) are robust to gaps.

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

const WEEK_MS = 7 * 24 * 60 * 60 * 1000

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
    const res = await fetch(url, { headers: { Authorization: `Bearer ${API_KEY}` } })
    const body = await res.text()
    let parsed
    try {
        parsed = JSON.parse(body)
    } catch {
        // A 200 with a non-JSON body (proxy interstitial, maintenance HTML) is still a failure.
        throw new Error(`${action} -> ${res.status}: non-JSON response (${body.slice(0, 120)})`)
    }
    if (!res.ok) {
        // The endpoint 400s with a clear `detail` when no GitHub source is connected.
        throw new Error(`${action} -> ${res.status}: ${parsed.detail || body}`)
    }
    return parsed
}

function fmtInt(n) {
    return Math.round(n).toLocaleString('en-US')
}

// Minutes at CI-bill scale: '3.04M' past a million, thousands-separated below.
function fmtMinutes(minutes) {
    return minutes >= 1_000_000 ? `${(minutes / 1_000_000).toFixed(2)}M` : fmtInt(minutes)
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
function fmtDelta(current, previous) {
    const pct = ((current - previous) / previous) * 100
    let s = pct.toFixed(1)
    if (s === '-0.0') {
        s = '0.0'
    }
    return s.startsWith('-') ? `${s}%` : `+${s}%`
}

// Merged-PR count for an overview window: the cost_series buckets are zero-filled and
// bucket-local (merges counted by merged_at), so their sum is the window's exact count.
// The series is empty until the github_workflow_jobs source syncs — null then.
function sumMerges(overview) {
    if (!overview.cost_series || overview.cost_series.length === 0) {
        return null
    }
    return overview.cost_series.reduce((total, bucket) => total + bucket.merges, 0)
}

function cell(text) {
    return { type: 'raw_text', text }
}

// One table row per metric, added only when both windows carry the value, so a
// not-yet-synced jobs source degrades to fewer rows instead of a broken message.
function tableRows(cur, prev) {
    const rows = []
    const add = (metric, curValue, prevValue, format) => {
        if (curValue == null || prevValue == null) {
            return
        }
        rows.push([cell(metric), cell(format(curValue)), cell(format(prevValue)), cell(fmtDelta(curValue, prevValue))])
    }
    // Null-propagating so `add`'s missing-value guard stays the only degradation path.
    const perPr = (minutes, merges) => (minutes != null && merges ? minutes / merges : null)
    add('CI minutes', cur.billable_minutes, prev.billable_minutes, fmtMinutes)
    add('min / merged PR', perPr(cur.billable_minutes, sumMerges(cur)), perPr(prev.billable_minutes, sumMerges(prev)), fmtInt)
    add('est. Depot $', cur.estimated_cost_usd, prev.estimated_cost_usd, fmtUsd)
    add('open→merge median', cur.median_open_to_merge_seconds, prev.median_open_to_merge_seconds, fmtLongDuration)
    add('re-run cycles', cur.rerun_cycles, prev.rerun_cycles, fmtInt)
    return rows
}

function buildBlocks(now, rows) {
    const dateLabel = now.toISOString().slice(0, 10)
    const blocks = [
        { type: 'section', text: { type: 'mrkdwn', text: `*Weekly CI — ${dateLabel}* _(vs prior week)_` } },
        {
            type: 'table',
            column_settings: [{ align: 'left' }, { align: 'right' }, { align: 'right' }, { align: 'right' }],
            rows: [[cell('metric'), cell('last week'), cell('prior week'), cell('Δ')], ...rows],
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
            text: 'Weekly CI digest', // notification fallback
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
        // No-op (don't fail the scheduled run) until the project + read key are wired.
        console.warn('POSTHOG_PROJECT_ID / POSTHOG_API_KEY not set — skipping digest. Wire them to enable.')
        return
    }
    const now = new Date()
    const thisFrom = new Date(now.getTime() - WEEK_MS).toISOString()
    const priorFrom = new Date(now.getTime() - 2 * WEEK_MS).toISOString()
    // Two window-scoped calls (not the endpoint's baked _prev twins) so the merged-count
    // sum and the other rows share windows exactly.
    const [cur, prev] = await Promise.all([
        api('repo_overview', { date_from: thisFrom, date_to: now.toISOString() }),
        api('repo_overview', { date_from: priorFrom, date_to: thisFrom }),
    ])
    const rows = tableRows(cur, prev)
    if (rows.length === 0) {
        // Every metric was null (key valid but nothing synced). Fail the job so the
        // breakage is visible instead of posting an empty table.
        throw new Error('repo_overview returned no usable metrics — not posting. Check the connected source.')
    }
    const blocks = buildBlocks(now, rows)
    if (DRY_RUN) {
        console.log(JSON.stringify(blocks, null, 2))
        return
    }
    if (!SLACK_BOT_TOKEN) {
        // Distinct from dry-run: a real run with no token is a misconfiguration, not a success.
        throw new Error('SLACK_BOT_TOKEN not set on a non-dry run — refusing to silently skip.')
    }
    await postToSlack(blocks)
    console.log(`Posted weekly CI digest to ${SLACK_CHANNEL}.`)
}

main().catch((err) => {
    console.error(err)
    process.exit(1)
})
