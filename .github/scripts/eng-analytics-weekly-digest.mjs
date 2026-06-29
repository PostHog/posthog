// Weekly engineering-analytics CI digest, posted to #alerts-devex on Monday.
//
// PULL model: this script reads the engineering_analytics product's own read
// endpoints (the same curated layer that backs its MCP tools and UI) and relays a
// week-over-week summary to Slack. It does NOT re-derive any metric from the GitHub
// API — the product owns the numbers, this owns the cadence + the Slack relay.
//
//   GHA cron ──> GET /api/projects/:id/engineering_analytics/<action>/ ──> Slack
//
// What it reports today:
//   - CI speed WoW: per-workflow p50/p95 duration on `master`, this 7d vs prior 7d,
//     ranked by % change. Scoped to one branch so the comparison is apples-to-apples
//     (master + PR runs blended would track the week's run-mix, not duration), and to
//     master specifically because its gating workflows don't supersede-cancel, so
//     cancelled-run durations barely pollute the percentile there.
//   - Backlog snapshot: open / stuck (>7d) / failing-CI PR counts.
//   - Quarantine debt: active / expiring / in-grace / overdue flaky-test quarantines.
//
// TODO(eng-analytics): two signals are NOT honestly computable from today's general
// endpoints and are intentionally omitted until a purpose-built weekly aggregate lands
// in products/engineering_analytics/backend (defined once in logic/, per SPEC §7):
//   - Throughput WoW (merged-PR count + median time-to-merge): pull_requests caps at
//     1000 rows ordered by created_at DESC and always includes every open PR, so on a
//     busy repo most in-window merges are dropped — biased, not just truncated.
//     Needs a weekly merged-count aggregate.
//   - Fully clean CI speed across all branches: workflow_health's p50/p95 is over
//     status='completed', which includes cancelled runs (no conclusion filter), so
//     off-master durations are polluted by supersede-cancels. Needs a conclusion=
//     'success', branch-scoped duration percentile.
//   - Total CI minutes / Depot $ WoW (the original ask): needs the github_workflow_jobs
//     source synced (cost endpoints return jobs_available=false until then) plus a
//     summed-minutes-by-week aggregate. Fold all three into one `weekly_summary`
//     endpoint and pull it here.

const HOST = (process.env.POSTHOG_HOST || 'https://us.posthog.com').replace(/\/$/, '')
const PROJECT_ID = process.env.POSTHOG_PROJECT_ID || ''
const API_KEY = process.env.POSTHOG_API_KEY || ''
const REPO = process.env.ENG_ANALYTICS_REPO || '' // 'owner/name', for the quarantine line
// Pin the source when the project has more than one connected GitHub source; otherwise
// the endpoints default to the oldest, which may not be the repo you mean.
const SOURCE_ID = process.env.ENG_ANALYTICS_SOURCE_ID || ''
const BRANCH = process.env.ENG_ANALYTICS_BRANCH || 'master' // CI-speed comparison branch
const SLACK_BOT_TOKEN = process.env.SLACK_BOT_TOKEN || ''
const SLACK_CHANNEL = process.env.SLACK_CHANNEL || 'C0AS64N6DJL' // #alerts-devex
const DRY_RUN = ['1', 'true', 'yes'].includes((process.env.DRY_RUN || '').toLowerCase())

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

function workflowKey(item) {
    return `${item.repo.owner}/${item.repo.name}:${item.workflow_name}`
}

// CI speed WoW — the headline. Per-workflow p50/p95 on BRANCH, this 7d vs prior 7d,
// ranked by percentage change so a fast workflow that doubled isn't hidden behind a
// large-but-flat slow one.
async function ciSpeedSection(now) {
    const thisFrom = new Date(now.getTime() - WEEK_MS).toISOString()
    const priorFrom = new Date(now.getTime() - 2 * WEEK_MS).toISOString()
    const [thisWeek, priorWeek] = await Promise.all([
        api('workflow_health', { date_from: thisFrom, date_to: now.toISOString(), branch: BRANCH }),
        api('workflow_health', { date_from: priorFrom, date_to: thisFrom, branch: BRANCH }),
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

// Quarantine debt — flaky tests parked past (or near) their expiry. file.entries spans
// every lifecycle, so count `active` explicitly rather than calling the total "active".
async function quarantineSection() {
    if (!REPO) {
        return null // no repo configured — nothing to report (distinct from "file missing" below)
    }
    const file = await api('quarantine', { repo: REPO })
    if (!file.available) {
        return `*Flaky-test quarantine*\n_No quarantine file for ${slackEscape(REPO)}._`
    }
    const tally = {}
    for (const e of file.entries) {
        tally[e.lifecycle] = (tally[e.lifecycle] || 0) + 1
    }
    const count = (lifecycle) => tally[lifecycle] || 0
    return [
        '*Flaky-test quarantine*',
        `• ${count('active')} active, ${count('expiring_soon')} expiring soon, ${count('in_grace')} in grace, ${count(
            'overdue'
        )} overdue`,
    ].join('\n')
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
        { name: 'CI speed', run: () => ciSpeedSection(now) },
        { name: 'Backlog', run: backlogSection },
        { name: 'Quarantine', run: quarantineSection },
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
    blocks.push({
        type: 'context',
        elements: [
            {
                type: 'mrkdwn',
                text: 'Source: engineering_analytics read endpoints · run-level data (no Depot $ yet) · /engineering-analytics',
            },
        ],
    })
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
