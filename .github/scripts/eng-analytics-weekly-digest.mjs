// Weekly engineering-analytics CI digest, posted to #alerts-devex on Monday.
//
// PULL model: this script reads the engineering_analytics product's own read
// endpoints (the same curated layer that backs its MCP tools and UI) and relays a
// week-over-week summary to Slack. It does NOT re-derive any metric from the GitHub
// API — the product owns the numbers, this owns the cadence + the Slack relay.
//
//   GHA cron ──> GET /api/projects/:id/engineering_analytics/<action>/ ──> Slack
//
// What it reports (this 7d vs prior 7d):
//   - Throughput & CI health: merged-PR count, median open→merge, CI success rate,
//     re-run cycles, billable (self-hosted) minutes and estimated Depot $ — all from
//     repo_overview, which computes them server-side (plain countIf/quantileIf, no
//     row caps), so the throughput numbers the first cut had to defer are honest now.
//   - CI speed WoW: per-workflow p50/p95 duration on `master`, ranked by % change.
//     Scoped to one branch so the comparison is apples-to-apples (master + PR runs
//     blended would track the week's run-mix, not duration), and to master
//     specifically because its gating workflows don't supersede-cancel, so
//     cancelled-run durations barely pollute the percentile there.
//
// Still deferred — signals the read layer can't compute honestly yet:
//   - A fully clean all-branch CI-speed percentile: workflow_health's p50/p95 is over
//     status='completed' with no conclusion filter, so off-master durations are
//     polluted by supersede-cancels. Needs a conclusion='success' percentile upstream.
//   - Test-level failure triage: master_failures groups at (workflow, de-sharded job)
//     level, which is dominated by rollup gate jobs ("X Tests Pass") and matrix shard
//     names — not actionable in a digest. The product's `flaky_tests` endpoint (per-test
//     leaderboard over CI test spans) is the right source; add that section once it
//     ships.
//
// Data caveat: the runs/jobs warehouse tables are webhook-fed and do not backfill a
// missed window, so a webhook outage undercounts that week's COUNT-based lines (runs,
// re-runs, billable minutes, $, failure totals) and the WoW delta absorbs the hole.
// Ratios (success rate, p50/p95) and the PR-snapshot lines (merged count, open→merge
// median) are robust to gaps.

const HOST = (process.env.POSTHOG_HOST || 'https://us.posthog.com').replace(/\/$/, '')
const PROJECT_ID = process.env.POSTHOG_PROJECT_ID || ''
const API_KEY = process.env.POSTHOG_API_KEY || ''
// Pin the source when the project has more than one connected GitHub source; otherwise
// the endpoints default to the oldest, which may not be the repo you mean.
const SOURCE_ID = process.env.ENG_ANALYTICS_SOURCE_ID || ''
const BRANCH = process.env.ENG_ANALYTICS_BRANCH || 'master' // CI-speed comparison branch
const SLACK_BOT_TOKEN = process.env.SLACK_BOT_TOKEN || ''
const SLACK_CHANNEL = process.env.SLACK_CHANNEL || 'C0AS64N6DJL' // #alerts-devex
const DRY_RUN = ['1', 'true', 'yes'].includes((process.env.DRY_RUN || '').toLowerCase())

// GitHub Actions sets these on every step; used to link the digest back to the run that posted it.
const GITHUB_SERVER_URL = process.env.GITHUB_SERVER_URL || 'https://github.com'
const GITHUB_REPOSITORY = process.env.GITHUB_REPOSITORY || ''
const GITHUB_RUN_ID = process.env.GITHUB_RUN_ID || ''
const GITHUB_WORKFLOW = process.env.GITHUB_WORKFLOW || 'Weekly CI digest'

function intEnv(name, fallback) {
    const raw = process.env[name]
    if (!raw) {
        return fallback
    }
    const n = Number(raw)
    return Number.isFinite(n) ? n : fallback
}

// Only compare workflows with at least this many runs in BOTH weeks, so a workflow that
// ran twice doesn't dominate the regression list with noise.
const MIN_RUNS = intEnv('MIN_RUNS', 5)
const TOP_N = intEnv('TOP_N', 5)

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
        // The endpoints 400 with a clear `detail` when no GitHub source is connected.
        throw new Error(`${action} -> ${res.status}: ${parsed.detail || body}`)
    }
    return parsed
}

// Slack mrkdwn treats &, <, > specially; escape any dynamic text before interpolating.
// Mirrors slackEscape in the sibling ci-alerts-devex.js.
function slackEscape(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

// CI run durations: seconds → '14m' / '3m20s' / '45s'.
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

// PR-lifecycle durations: seconds → '3d4h' / '7h05m' / '42m'. Coarser units than
// fmtDuration because open→merge lives on an hours-to-days scale.
function fmtLongDuration(seconds) {
    if (seconds == null) {
        return 'n/a'
    }
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

// '14m→17m' — a prior→current pair of CI durations.
function fmtTransition(prior, current) {
    return `${fmtDuration(prior)}→${fmtDuration(current)}`
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
    // Math.round(-0.3) is -0, which stringifies to '0' and isn't > 0, so a sub-0.5% dip reads '(0%)'.
    const rounded = Math.round(p)
    const sign = rounded > 0 ? '+' : ''
    return ` (${sign}${rounded}%)`
}

// Billable CI minutes, thousands-separated whole minutes ('12,345m'). Compute minutes
// (parallel jobs sum), not wall-clock.
function fmtMinutes(minutes) {
    return `${Math.round(minutes).toLocaleString('en-US')}m`
}

// Estimated dollars, no cents ('$1,234').
function fmtUsd(amount) {
    return `$${Math.round(amount).toLocaleString('en-US')}`
}

// 0..1 rate → '92.1%'.
function fmtRate(rate) {
    return `${(rate * 100).toFixed(1)}%`
}

// Success-rate deltas are percentage-POINT changes, not relative % — '(+1.3pp)'.
function fmtPpDelta(current, previous) {
    const delta = (current - previous) * 100
    const sign = delta > 0 ? '+' : ''
    return ` (${sign}${delta.toFixed(1)}pp)`
}

function workflowKey(item) {
    return `${item.repo.owner}/${item.repo.name}:${item.workflow_name}`
}

// The [date_from, date_to] pairs for this 7d and the prior 7d, as ISO strings.
function weekWindows(now) {
    const thisFrom = new Date(now.getTime() - WEEK_MS).toISOString()
    const priorFrom = new Date(now.getTime() - 2 * WEEK_MS).toISOString()
    return [
        { date_from: thisFrom, date_to: now.toISOString() },
        { date_from: priorFrom, date_to: thisFrom },
    ]
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

// Throughput & CI health WoW — repo_overview's server-side aggregates for this 7d vs
// the prior 7d (two window-scoped calls; each window's own figures, not the endpoint's
// baked _prev twins, so the merged-count sum and the other lines share windows exactly).
// The endpoint aggregates across the whole connected source — for a single-repo source
// that is the repo. Lines degrade independently: merged counts and the cost lines are
// null until the github_workflow_jobs source syncs; medians and rates never need it.
async function headlineSection(now) {
    const [thisWin, priorWin] = weekWindows(now)
    const [thisWeek, priorWeek] = await Promise.all([api('repo_overview', thisWin), api('repo_overview', priorWin)])

    const lines = ['*Throughput & CI health — all branches (vs prior week)*']
    const thisMerges = sumMerges(thisWeek)
    const priorMerges = sumMerges(priorWeek)
    if (thisMerges != null && priorMerges != null) {
        // Bots included — matches the endpoint's merge population (and CI cost's denominator).
        lines.push(
            `• Merged PRs (incl. bots): ${priorMerges.toLocaleString('en-US')}→${thisMerges.toLocaleString(
                'en-US'
            )}${fmtPct(pctChange(thisMerges, priorMerges))}`
        )
    }
    if (thisWeek.median_open_to_merge_seconds != null && priorWeek.median_open_to_merge_seconds != null) {
        // Coarse by design (draft + ready-for-review fused); bots and drafts excluded upstream.
        lines.push(
            `• Median open→merge (bots/drafts excluded): ${fmtLongDuration(
                priorWeek.median_open_to_merge_seconds
            )}→${fmtLongDuration(thisWeek.median_open_to_merge_seconds)}${fmtPct(
                pctChange(thisWeek.median_open_to_merge_seconds, priorWeek.median_open_to_merge_seconds)
            )}`
        )
    }
    if (thisWeek.success_rate != null && priorWeek.success_rate != null) {
        lines.push(
            `• CI success rate: ${fmtRate(priorWeek.success_rate)}→${fmtRate(thisWeek.success_rate)}${fmtPpDelta(
                thisWeek.success_rate,
                priorWeek.success_rate
            )}`
        )
    }
    lines.push(
        `• Re-run cycles: ${priorWeek.rerun_cycles.toLocaleString('en-US')}→${thisWeek.rerun_cycles.toLocaleString(
            'en-US'
        )}${fmtPct(pctChange(thisWeek.rerun_cycles, priorWeek.rerun_cycles))}`
    )
    if (thisWeek.billable_minutes != null && priorWeek.billable_minutes != null) {
        lines.push(
            `• Billable minutes: ${fmtMinutes(priorWeek.billable_minutes)}→${fmtMinutes(
                thisWeek.billable_minutes
            )}${fmtPct(pctChange(thisWeek.billable_minutes, priorWeek.billable_minutes))}`
        )
    }
    if (thisWeek.estimated_cost_usd != null && priorWeek.estimated_cost_usd != null) {
        lines.push(
            `• Est. Depot spend: ${fmtUsd(priorWeek.estimated_cost_usd)}→${fmtUsd(thisWeek.estimated_cost_usd)}${fmtPct(
                pctChange(thisWeek.estimated_cost_usd, priorWeek.estimated_cost_usd)
            )}`
        )
    }
    return lines.join('\n')
}

// CI speed WoW — per-workflow p50/p95 on BRANCH, this 7d vs prior 7d, ranked by
// percentage change so a fast workflow that doubled isn't hidden behind a
// large-but-flat slow one.
async function ciSpeedSection(now) {
    const [thisWin, priorWin] = weekWindows(now)
    const [thisWeek, priorWeek] = await Promise.all([
        api('workflow_health', { ...thisWin, branch: BRANCH }),
        api('workflow_health', { ...priorWin, branch: BRANCH }),
    ])
    const priorByKey = new Map(priorWeek.map((w) => [workflowKey(w), w]))

    const compared = []
    for (const w of thisWeek) {
        const prior = priorByKey.get(workflowKey(w))
        if (!prior || w.run_count < MIN_RUNS || prior.run_count < MIN_RUNS) {
            continue
        }
        if (w.p50_seconds == null || prior.p50_seconds == null) {
            continue
        }
        compared.push({
            repo: `${w.repo.owner}/${w.repo.name}`,
            name: w.workflow_name,
            p50: w.p50_seconds,
            p50Prior: prior.p50_seconds,
            p50Pct: pctChange(w.p50_seconds, prior.p50_seconds),
            p95: w.p95_seconds,
            p95Prior: prior.p95_seconds,
        })
    }

    const header = `*CI speed — \`${BRANCH}\` (p50/p95, vs prior week)*`
    if (compared.length === 0) {
        return `${header}\n_No workflow had ≥${MIN_RUNS} runs in both weeks to compare._`
    }

    // Qualify with the repo only when the source spans more than one, so single-repo
    // digests stay terse but multi-repo ones aren't ambiguous.
    const multiRepo = new Set(compared.map((c) => c.repo)).size > 1
    const label = (c) => slackEscape(multiRepo ? `${c.repo} ${c.name}` : c.name)

    const ranked = compared.filter((c) => c.p50Pct != null).sort((a, b) => b.p50Pct - a.p50Pct)
    const slower = ranked.filter((c) => c.p50Pct > 0).slice(0, TOP_N)
    // Two biggest speedups, biggest first.
    const faster = ranked.filter((c) => c.p50Pct < 0).sort((a, b) => a.p50Pct - b.p50Pct).slice(0, 2)

    const lines = [header]
    if (slower.length) {
        lines.push('🔺 Slower:')
        for (const c of slower) {
            lines.push(
                `• \`${label(c)}\` — p50 ${fmtTransition(c.p50Prior, c.p50)}${fmtPct(c.p50Pct)}, p95 ${fmtTransition(
                    c.p95Prior,
                    c.p95
                )}`
            )
        }
    }
    if (faster.length) {
        lines.push('🟢 Faster:')
        for (const c of faster) {
            lines.push(`• \`${label(c)}\` — p50 ${fmtTransition(c.p50Prior, c.p50)}${fmtPct(c.p50Pct)}`)
        }
    }
    return lines.join('\n')
}

// Returns { blocks, succeeded } — succeeded counts sections that produced content, so
// main can refuse to post (and fail loudly) when every section errored.
async function buildDigest(now) {
    const dateLabel = now.toISOString().slice(0, 10)
    const blocks = [
        { type: 'header', text: { type: 'plain_text', text: `📈 Weekly CI digest — ${dateLabel}`, emoji: true } },
    ]
    // Run each section independently — one failing endpoint shouldn't sink the digest. Named so a
    // failure block can say which section broke, not just the raw error.
    const sections = [
        { name: 'Throughput & CI health', run: () => headlineSection(now) },
        { name: 'CI speed', run: () => ciSpeedSection(now) },
    ]
    const results = await Promise.allSettled(sections.map((s) => s.run()))
    let succeeded = 0
    results.forEach((r, i) => {
        if (r.status === 'rejected') {
            blocks.push({
                type: 'section',
                text: { type: 'mrkdwn', text: `⚠️ _${sections[i].name} failed: ${slackEscape(r.reason.message)}_` },
            })
        } else if (r.value) {
            succeeded += 1
            blocks.push({ type: 'section', text: { type: 'mrkdwn', text: r.value } })
        }
    })
    // Provenance: link back to the Actions run that posted this. Only in CI (no run id locally).
    if (GITHUB_REPOSITORY && GITHUB_RUN_ID) {
        const runUrl = `${GITHUB_SERVER_URL}/${GITHUB_REPOSITORY}/actions/runs/${GITHUB_RUN_ID}`
        blocks.push({
            type: 'context',
            elements: [{ type: 'mrkdwn', text: `<${runUrl}|${slackEscape(GITHUB_WORKFLOW)}>` }],
        })
    }
    return { blocks, succeeded }
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
    const { blocks, succeeded } = await buildDigest(now)
    if (succeeded === 0) {
        // Every section errored (bad key/scope, disconnected source, API down). Don't post a
        // digest of only "Section failed" lines — fail the job so the breakage is visible.
        throw new Error('All digest sections failed — not posting. Check the API key scope and connected source.')
    }
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
