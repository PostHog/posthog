// Weekly engineering-analytics CI digest, posted to #alerts-devex on Monday.
//
// PULL model: this script reads the engineering_analytics product's own read
// endpoints (the same curated layer that backs its MCP tools and UI) and relays a
// week-over-week summary to Slack. It does NOT re-derive any metric from the GitHub
// API — the product owns the numbers, this owns the cadence + the Slack relay.
//
//   GHA cron ──> GET /api/projects/:id/engineering_analytics/<action>/ ──> Slack
//
// What it reports today (everything below is computable from run-level warehouse
// data — github_workflow_runs + github_pull_requests — already synced):
//   - CI speed WoW: per-workflow p50/p95 duration, this 7d vs the prior 7d. Precise
//     (runs are immutable). This is the headline "is CI getting slower" drumbeat.
//   - Throughput WoW: merged-PR count + median open-to-merge, this 7d vs prior 7d.
//   - Backlog snapshot: open / stuck (>7d) / failing-CI PR counts.
//   - Quarantine debt: overdue + expiring-soon flaky-test quarantines.
//
// What it deliberately does NOT report yet (see PR description):
//   - Total CI minutes / Depot $ WoW — Paul's literal ask. No endpoint returns a
//     summed-minutes figure, and $ needs the github_workflow_jobs source (cost
//     endpoints return jobs_available=false until it syncs). Needs a small
//     sum(duration_seconds)-by-week aggregate in the read layer (follow-up).
//   - CI re-run waste WoW — pull_requests exposes rerun_cycles/pushes as per-PR
//     LIFETIME counts, not time-bucketed, so they can't be summed into "reruns this
//     week". Also needs a new weekly aggregate (follow-up).

const HOST = (process.env.POSTHOG_HOST || 'https://us.posthog.com').replace(/\/$/, '')
const PROJECT_ID = process.env.POSTHOG_PROJECT_ID || ''
const API_KEY = process.env.POSTHOG_API_KEY || ''
const REPO = process.env.ENG_ANALYTICS_REPO || '' // 'owner/name', for the quarantine line
const SOURCE_ID = process.env.ENG_ANALYTICS_SOURCE_ID || '' // optional; defaults to oldest source
const SLACK_BOT_TOKEN = process.env.SLACK_BOT_TOKEN || ''
const SLACK_CHANNEL = process.env.SLACK_CHANNEL || 'C0AS64N6DJL' // #alerts-devex
const DRY_RUN = ['1', 'true', 'yes'].includes((process.env.DRY_RUN || '').toLowerCase())

// Only compare workflows with at least this many runs in BOTH weeks, so a workflow
// that ran twice doesn't dominate the regression list with noise.
const MIN_RUNS = Number(process.env.MIN_RUNS || 5)
const TOP_N = Number(process.env.TOP_N || 5)

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
    if (!res.ok) {
        // The endpoints 400 with a clear `detail` when no GitHub source is connected.
        let detail = body
        try {
            detail = JSON.parse(body).detail || body
        } catch {
            // keep raw body
        }
        throw new Error(`${action} -> ${res.status}: ${detail}`)
    }
    return JSON.parse(body)
}

function fmtDuration(seconds) {
    if (seconds == null) {
        return 'n/a'
    }
    const total = Math.round(seconds)
    const m = Math.floor(total / 60)
    const s = total % 60
    if (m === 0) {
        return `${s}s`
    }
    return s === 0 ? `${m}m` : `${m}m${s}s`
}

function pctChange(current, previous) {
    if (previous == null || current == null || previous === 0) {
        return null
    }
    return ((current - previous) / previous) * 100
}

function fmtPct(p) {
    if (p == null) {
        return ''
    }
    const sign = p >= 0 ? '+' : ''
    return ` (${sign}${p.toFixed(0)}%)`
}

function median(values) {
    const nums = values.filter((v) => v != null).sort((a, b) => a - b)
    if (nums.length === 0) {
        return null
    }
    const mid = Math.floor(nums.length / 2)
    return nums.length % 2 ? nums[mid] : (nums[mid - 1] + nums[mid]) / 2
}

function workflowKey(item) {
    return `${item.repo.owner}/${item.repo.name}:${item.workflow_name}`
}

// CI speed WoW — the headline. Per-workflow p50/p95 this 7d vs the prior 7d.
async function ciSpeedSection(now) {
    const thisFrom = new Date(now.getTime() - WEEK_MS).toISOString()
    const priorFrom = new Date(now.getTime() - 2 * WEEK_MS).toISOString()
    const priorTo = thisFrom
    const [thisWeek, priorWeek] = await Promise.all([
        api('workflow_health', { date_from: thisFrom, date_to: now.toISOString() }),
        api('workflow_health', { date_from: priorFrom, date_to: priorTo }),
    ])
    const priorByKey = new Map(priorWeek.map((w) => [workflowKey(w), w]))

    const compared = []
    for (const w of thisWeek) {
        const prior = priorByKey.get(workflowKey(w))
        if (!prior) {
            continue
        }
        if (w.run_count < MIN_RUNS || prior.run_count < MIN_RUNS) {
            continue
        }
        if (w.p50_seconds == null || prior.p50_seconds == null) {
            continue
        }
        compared.push({
            name: w.workflow_name,
            p50: w.p50_seconds,
            p50Prior: prior.p50_seconds,
            p50Delta: w.p50_seconds - prior.p50_seconds,
            p95: w.p95_seconds,
            p95Prior: prior.p95_seconds,
        })
    }

    if (compared.length === 0) {
        return '*CI speed (p50/p95, vs prior week)*\n_No workflow had ≥' + MIN_RUNS + ' runs in both weeks to compare._'
    }

    compared.sort((a, b) => b.p50Delta - a.p50Delta)
    const slower = compared.filter((c) => c.p50Delta > 0).slice(0, TOP_N)
    const faster = compared.filter((c) => c.p50Delta < 0).slice(-2).reverse()

    const lines = ['*CI speed (p50/p95, vs prior week)*']
    if (slower.length) {
        lines.push('🔺 Slower:')
        for (const c of slower) {
            lines.push(
                `• \`${c.name}\` — p50 ${fmtDuration(c.p50Prior)}→${fmtDuration(c.p50)}${fmtPct(
                    pctChange(c.p50, c.p50Prior)
                )}, p95 ${fmtDuration(c.p95Prior)}→${fmtDuration(c.p95)}`
            )
        }
    }
    if (faster.length) {
        lines.push('🟢 Faster:')
        for (const c of faster) {
            lines.push(
                `• \`${c.name}\` — p50 ${fmtDuration(c.p50Prior)}→${fmtDuration(c.p50)}${fmtPct(
                    pctChange(c.p50, c.p50Prior)
                )}`
            )
        }
    }
    return lines.join('\n')
}

// Throughput WoW — merged-PR count + median open-to-merge. Note: pull_requests caps
// at 1000 rows; over a 14d window on a busy repo this can truncate, which would
// undercount. We surface `truncated` honestly rather than imply a complete count.
async function throughputSection(now) {
    const fromIso = new Date(now.getTime() - 2 * WEEK_MS).toISOString()
    const result = await api('pull_requests', { date_from: fromIso })
    const thisStart = now.getTime() - WEEK_MS
    const priorStart = now.getTime() - 2 * WEEK_MS

    const weekStats = (start, end) => {
        const merged = result.items.filter((pr) => {
            if (pr.state !== 'merged' || !pr.merged_at) {
                return false
            }
            const t = new Date(pr.merged_at).getTime()
            return t >= start && t < end
        })
        return {
            count: merged.length,
            medianOpenToMerge: median(merged.map((pr) => pr.open_to_merge_seconds)),
        }
    }
    const thisWeek = weekStats(thisStart, now.getTime())
    const priorWeek = weekStats(priorStart, thisStart)

    const lines = ['*Throughput (merged PRs, vs prior week)*']
    lines.push(
        `• Merged: ${thisWeek.count} vs ${priorWeek.count}${fmtPct(pctChange(thisWeek.count, priorWeek.count))}`
    )
    lines.push(
        `• Median open→merge: ${fmtDuration(thisWeek.medianOpenToMerge)} vs ${fmtDuration(
            priorWeek.medianOpenToMerge
        )} _(coarse: fuses draft + ready time)_`
    )
    if (result.truncated) {
        lines.push(`⚠️ PR list truncated at ${result.limit} — counts may undercount. Needs a dedicated weekly aggregate.`)
    }
    return lines.join('\n')
}

// Backlog snapshot — current state, not a trend.
async function backlogSection() {
    const cards = await api('ci_cards')
    return [
        '*Backlog (now)*',
        `• Open PRs: ${cards.open_prs} across ${cards.repos} repo(s)`,
        `• Stuck (>7d, non-draft, non-bot): ${cards.stuck}`,
        `• With failing CI: ${cards.failing_ci}`,
    ].join('\n')
}

// Quarantine debt — flaky tests parked past (or near) their expiry.
async function quarantineSection() {
    if (!REPO) {
        return null
    }
    const file = await api('quarantine', { repo: REPO })
    if (!file.available) {
        return null
    }
    const overdue = file.entries.filter((e) => e.lifecycle === 'overdue').length
    const inGrace = file.entries.filter((e) => e.lifecycle === 'in_grace').length
    const expiring = file.entries.filter((e) => e.lifecycle === 'expiring_soon').length
    return [
        '*Flaky-test quarantine*',
        `• ${file.entries.length} active, ${overdue} overdue, ${inGrace} in grace, ${expiring} expiring soon`,
    ].join('\n')
}

async function buildBlocks(now) {
    const dateLabel = now.toISOString().slice(0, 10)
    const blocks = [
        { type: 'header', text: { type: 'plain_text', text: `📈 Weekly CI digest — ${dateLabel}`, emoji: true } },
    ]
    // Run each section independently — one failing endpoint shouldn't sink the digest.
    const sections = [ciSpeedSection(now), throughputSection(now), backlogSection(), quarantineSection()]
    const results = await Promise.allSettled(sections)
    for (const r of results) {
        if (r.status === 'fulfilled') {
            if (r.value) {
                blocks.push({ type: 'section', text: { type: 'mrkdwn', text: r.value } })
            }
        } else {
            blocks.push({ type: 'section', text: { type: 'mrkdwn', text: `⚠️ _Section failed: ${r.reason.message}_` } })
        }
    }
    blocks.push({
        type: 'context',
        elements: [
            {
                type: 'mrkdwn',
                text: 'Source: engineering_analytics read endpoints · run-level data (no Depot $ yet) · /engineering-analytics',
            },
        ],
    })
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
    const blocks = await buildBlocks(now)
    if (DRY_RUN || !SLACK_BOT_TOKEN) {
        console.log(JSON.stringify(blocks, null, 2))
        if (!SLACK_BOT_TOKEN) {
            console.warn('SLACK_BOT_TOKEN not set — printed digest instead of posting.')
        }
        return
    }
    await postToSlack(blocks)
    console.log(`Posted weekly CI digest to ${SLACK_CHANNEL}.`)
}

main().catch((err) => {
    console.error(err)
    process.exit(1)
})
