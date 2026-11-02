// Weekly CI digest, posted to #alerts-devex on Monday.
//
// It reports the last 7 complete UTC days next to the 7 days before them, in one Slack table.
// Spend is what Depot bills, at Depot's prices, for every repository in the organization:
//
//   - runners: minutes Depot billed for GitHub Actions jobs, from Depot's usage API. The minutes are
//     already weighted by runner size, the way Depot counts them.
//   - Depot CI: run time of every Depot CI job attempt, from the engineering_analytics
//     depot_ci_usage endpoint. Depot's usage API has no Depot CI figures. The endpoint covers the
//     repositories that have a Depot source in the PostHog project, and a context line names them.
//   - container builds: minutes Depot billed for image builds, from Depot's usage API.
//
// The other rows cover this repository only. `$ / merged PR` divides this repository's runner and
// Depot CI spend by its merged pull requests, bots included. `ready→merge median` comes from the
// engineering_analytics repo_overview endpoint, and falls back to the open→merge median when the
// draft and ready transitions are not synced.
//
// A sentence under the table says how much of the Depot contract is used and when it runs out at
// last week's spend. Cache storage is not counted. Depot CI counts only the attempts the warehouse
// holds, so Depot CI that ran before a Depot source started syncing is missing from the total.
//
// The digest posts without the spend rows when Depot's API or the depot_ci_usage endpoint fails,
// and without the contract sentence when the contract variables are not set.

import { pathToFileURL } from 'node:url'

const HOST = (process.env.POSTHOG_HOST || 'https://us.posthog.com').replace(/\/$/, '')
const PROJECT_ID = process.env.POSTHOG_PROJECT_ID || ''
const API_KEY = process.env.POSTHOG_API_KEY || ''
// Pins the GitHub source when the project has more than one. Otherwise the oldest one answers.
const SOURCE_ID = process.env.ENG_ANALYTICS_SOURCE_ID || ''
const SLACK_BOT_TOKEN = process.env.SLACK_BOT_TOKEN || ''
const SLACK_CHANNEL = process.env.SLACK_CHANNEL || 'C0AS64N6DJL' // #alerts-devex
const DRY_RUN = ['1', 'true', 'yes'].includes((process.env.DRY_RUN || '').toLowerCase())

const GITHUB_SERVER_URL = process.env.GITHUB_SERVER_URL || 'https://github.com'
const GITHUB_REPOSITORY = process.env.GITHUB_REPOSITORY || ''
// 'owner/repo/.github/workflows/x.yml@refs/heads/master', set by Actions on every run, so the
// digest's link to this workflow survives a rename of the file.
const GITHUB_WORKFLOW_REF = process.env.GITHUB_WORKFLOW_REF || ''
const GITHUB_REF_NAME = process.env.GITHUB_REF_NAME || 'master'

// The contract terms come from repository variables, so a renewal needs no code change.
const DEPOT_TOKEN = process.env.DEPOT_TOKEN || ''
const DEPOT_CONTRACT_USD = Number(process.env.DEPOT_CONTRACT_USD || 0)
const DEPOT_CONTRACT_START = process.env.DEPOT_CONTRACT_START || ''
const DEPOT_CONTRACT_END = process.env.DEPOT_CONTRACT_END || ''

// Depot's price per billed minute. Depot CI is priced by the depot_ci_usage endpoint.
const RUNNER_USD_PER_MINUTE = 0.004
const BUILD_USD_PER_MINUTE = 0.04

const DAY_MS = 24 * 60 * 60 * 1000
const WEEK_MS = 7 * DAY_MS

function billedMinutes(entry) {
    // Protobuf JSON omits scalar fields at their zero default.
    const minutes = entry?.minutesBilled ?? 0
    if (!Number.isFinite(minutes) || minutes < 0) {
        throw new Error('Depot GetUsage returned invalid billed minutes')
    }
    return minutes
}

// Runner and container build spend Depot reports for [startAt, endAt), for the whole organization
// and for this repository.
async function depotUsageSpend(startAt, endAt) {
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
    const builds = usage?.containerBuild ?? []
    if (!usage || typeof usage !== 'object' || !Array.isArray(jobs) || !Array.isArray(builds)) {
        throw new Error('Depot GetUsage returned invalid usage')
    }
    let runners = 0
    let repoRunners = 0
    for (const repo of jobs) {
        if (!repo?.total) {
            throw new Error('Depot GetUsage returned a repository without totals')
        }
        const usd = billedMinutes(repo.total) * RUNNER_USD_PER_MINUTE
        runners += usd
        if (isThisRepository(repo.repo)) {
            repoRunners += usd
        }
    }
    const containerBuilds = builds.reduce((sum, project) => sum + billedMinutes(project) * BUILD_USD_PER_MINUTE, 0)
    return { runners, repoRunners, containerBuilds }
}

// Depot CI spend for [startAt, endAt), per repository with a synced Depot source.
async function depotCiSpend(startAt, endAt) {
    const usage = await apiWithRetry('depot_ci_usage', {
        date_from: startAt.toISOString(),
        date_to: endAt.toISOString(),
    })
    if (!Array.isArray(usage) || usage.some((repo) => !Number.isFinite(repo?.estimated_cost_usd))) {
        throw new Error('depot_ci_usage returned invalid usage')
    }
    return {
        depotCi: usage.reduce((sum, repo) => sum + repo.estimated_cost_usd, 0),
        repoDepotCi: usage
            .filter((repo) => isThisRepository(repo.repo))
            .reduce((sum, repo) => sum + repo.estimated_cost_usd, 0),
        depotCiRepos: usage.map((repo) => repo.repo),
    }
}

function isThisRepository(name) {
    return typeof name === 'string' && name.toLowerCase() === GITHUB_REPOSITORY.toLowerCase()
}

async function spend(startAt, endAt) {
    const [usage, ci] = await Promise.all([depotUsageSpend(startAt, endAt), depotCiSpend(startAt, endAt)])
    return { ...usage, ...ci, total: usage.runners + ci.depotCi + usage.containerBuilds }
}

function contractDates(weekEnd) {
    const start = new Date(`${DEPOT_CONTRACT_START}T00:00:00Z`)
    const end = new Date(`${DEPOT_CONTRACT_END}T00:00:00Z`)
    const valid =
        Number.isFinite(DEPOT_CONTRACT_USD) &&
        DEPOT_CONTRACT_USD > 0 &&
        Number.isFinite(start.getTime()) &&
        Number.isFinite(end.getTime()) &&
        isoDay(start) === DEPOT_CONTRACT_START &&
        isoDay(end) === DEPOT_CONTRACT_END &&
        start < weekEnd &&
        end > weekEnd
    return valid ? { start, end } : null
}

// Spend for the reported week, the week before it, and the contract so far, or null when any of it
// cannot be read. The digest then posts without spend, because a partial total would mislead.
async function readSpend(weekStart, weekEnd) {
    if (!DEPOT_TOKEN) {
        console.warn('DEPOT_TOKEN not set. Posting without spend.')
        return null
    }
    const contract = contractDates(weekEnd)
    if (!contract) {
        console.warn('Depot contract variables missing or invalid. Posting without the contract sentence.')
    }
    try {
        const [lastWeek, priorWeek, contractToDate] = await Promise.all([
            spend(weekStart, weekEnd),
            spend(new Date(weekStart.getTime() - WEEK_MS), weekStart),
            contract ? spend(contract.start, weekEnd) : null,
        ])
        return { lastWeek, priorWeek, contract: contract && { ...contract, used: contractToDate.total } }
    } catch (err) {
        // A Depot error stays out of the public Actions log, because a parse error can quote billing data.
        const reason = err.message.startsWith('depot_ci_usage') ? ` (${err.message})` : ''
        console.warn(`Spend unavailable${reason}. Posting without spend.`)
        return null
    }
}

function isoDay(date) {
    return date.toISOString().slice(0, 10)
}

function contractSummary(contract, weeklySpend, weekEnd) {
    const used = `Depot contract: ${fmtUsd(contract.used)} of ${fmtUsd(DEPOT_CONTRACT_USD)} used through ${isoDay(new Date(weekEnd.getTime() - DAY_MS))}, counting runners, Depot CI and container builds. Cache storage is not counted.`
    const remaining = DEPOT_CONTRACT_USD - contract.used
    if (remaining <= 0) {
        return `${used} The contract is used up.`
    }
    if (!(weeklySpend > 0)) {
        return used
    }
    const remainingDays = remaining / (weeklySpend / 7)
    const daysLeft = (contract.end.getTime() - weekEnd.getTime()) / DAY_MS
    const end = isoDay(contract.end)
    const daysShort = Math.round(daysLeft - remainingDays)
    if (daysShort <= 0) {
        return `${used} At last week's spend it lasts until the contract ends on ${end}.`
    }
    const runOut = new Date(weekEnd.getTime() + remainingDays * DAY_MS)
    return `${used} At last week's spend it runs out around ${isoDay(runOut)}, ${daysShort} days before the contract ends on ${end}.`
}

async function api(action, params) {
    const url = new URL(`${HOST}/api/projects/${PROJECT_ID}/engineering_analytics/${action}/`)
    for (const [k, v] of Object.entries(params)) {
        if (v) {
            url.searchParams.set(k, v)
        }
    }
    // Bounds every attempt. The gateway answers within about 2 minutes, so this only catches a hung
    // connection, and the worst case of all retries stays inside the workflow's timeout-minutes.
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
        // The endpoints answer only in JSON. Anything else is a proxy or maintenance page, so retry.
        fail(`non-JSON response (${body.slice(0, 120)})`, true)
    }
    if (!res.ok) {
        // A 4xx is a configuration error that a retry cannot fix. A 5xx or 429 can pass.
        fail(parsed?.detail || body, res.status >= 500 || res.status === 429)
    }
    return parsed
}

const RETRY_ATTEMPTS = 3
const RETRY_DELAY_MS = 30_000

// The warehouse queries share a ClickHouse cluster with everything else, and a busy Monday morning
// can push one attempt past the API gateway's timeout. Network errors and aborts retry too.
async function apiWithRetry(action, params) {
    for (let attempt = 1; ; attempt++) {
        try {
            return await api(action, params)
        } catch (err) {
            if (err.retryable === false || attempt >= RETRY_ATTEMPTS) {
                throw err
            }
            console.warn(`${err.message}. Attempt ${attempt}/${RETRY_ATTEMPTS}, retrying in ${RETRY_DELAY_MS / 1000}s.`)
            await new Promise((resolve) => setTimeout(resolve, RETRY_DELAY_MS))
        }
    }
}

function fmtInt(n) {
    return Math.round(n).toLocaleString('en-US')
}

function fmtUsd(amount) {
    return `$${fmtInt(amount)}`
}

// Seconds as '3d4h', '7h55m' or '42m'.
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

// Signed change with one decimal: '+66.5%', '-1.0%'. A change from zero has no finite percent,
// so it reads '+∞%', and zero to zero reads '+0.0%'.
function fmtDelta(current, previous) {
    if (previous === 0) {
        return current === 0 ? '+0.0%' : '+∞%'
    }
    let s = (((current - previous) / previous) * 100).toFixed(1)
    if (s === '-0.0') {
        s = '0.0'
    }
    return s.startsWith('-') ? `${s}%` : `+${s}%`
}

function cell(text) {
    return { type: 'raw_text', text }
}

const HIDDEN = 'hidden in dry runs'

// One row per metric. A metric is left out when either week lacks it, so a source that is not
// synced yet gives a shorter table instead of a broken one.
function tableRows(overview, weeks) {
    const rows = []
    const add = (metric, current, previous, format) => {
        if (current == null || previous == null) {
            return
        }
        // Actions logs are public, so a dry run prints no spend.
        rows.push(
            DRY_RUN && format === fmtUsd
                ? [cell(metric), cell(HIDDEN), cell(HIDDEN), cell(HIDDEN)]
                : [cell(metric), cell(format(current)), cell(format(previous)), cell(fmtDelta(current, previous))]
        )
    }
    if (weeks) {
        const [last, prior] = [weeks.lastWeek, weeks.priorWeek]
        const perPr = (week, merges) => (merges ? (week.repoRunners + week.repoDepotCi) / merges : null)
        add('Depot spend', last.total, prior.total, fmtUsd)
        add('└ runners', last.runners, prior.runners, fmtUsd)
        add('└ Depot CI', last.depotCi, prior.depotCi, fmtUsd)
        add('└ container builds', last.containerBuilds, prior.containerBuilds, fmtUsd)
        add('$ / merged PR', perPr(last, overview.merged_pr_count), perPr(prior, overview.merged_pr_count_prev), fmtUsd)
    }
    add('merged PRs', overview.merged_pr_count, overview.merged_pr_count_prev, fmtInt)
    // Both weeks need ready→merge to compare like with like, so a repository without the issue-events
    // sync, or a week that straddles its first sync, shows open→merge instead.
    const ready = overview.median_ready_to_merge_seconds != null && overview.median_ready_to_merge_seconds_prev != null
    add(
        ready ? 'ready→merge median' : 'open→merge median',
        ready ? overview.median_ready_to_merge_seconds : overview.median_open_to_merge_seconds,
        ready ? overview.median_ready_to_merge_seconds_prev : overview.median_open_to_merge_seconds_prev,
        fmtLongDuration
    )
    return rows
}

function buildBlocks(weekStart, weekEnd, rows, notes) {
    const lastDay = new Date(weekEnd.getTime() - DAY_MS)
    const blocks = [
        {
            type: 'section',
            text: { type: 'mrkdwn', text: `*Weekly CI, ${isoDay(weekStart)} to ${isoDay(lastDay)} UTC*` },
        },
        {
            type: 'table',
            column_settings: [{ align: 'left' }, { align: 'right' }, { align: 'right' }, { align: 'right' }],
            rows: [[cell(''), cell('last week'), cell('week before'), cell('change')], ...rows],
        },
    ]
    for (const note of notes) {
        blocks.push({ type: 'section', text: { type: 'mrkdwn', text: note } })
    }
    const workflowPath = GITHUB_WORKFLOW_REF.split('@')[0].replace(`${GITHUB_REPOSITORY}/`, '')
    if (GITHUB_REPOSITORY && workflowPath) {
        const editUrl = `${GITHUB_SERVER_URL}/${GITHUB_REPOSITORY}/edit/${GITHUB_REF_NAME}/${workflowPath}`
        blocks.push({ type: 'context', elements: [{ type: 'mrkdwn', text: `<${editUrl}|Edit this workflow>` }] })
    }
    return blocks
}

function spendNotes(weeks, weekEnd) {
    if (!weeks) {
        return []
    }
    const repos = weeks.lastWeek.depotCiRepos
    const notes = [
        repos.length
            ? `Depot CI counts ${repos.join(', ')}.`
            : 'Depot CI counts no repository: no Depot source is synced.',
    ]
    if (weeks.contract) {
        notes.push(
            DRY_RUN
                ? `Depot contract sentence ${HIDDEN}.`
                : contractSummary(weeks.contract, weeks.lastWeek.total, weekEnd)
        )
    }
    return notes
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
        // A scheduled run without these does nothing instead of failing every week.
        console.warn('POSTHOG_PROJECT_ID or POSTHOG_API_KEY not set. Skipping the digest.')
        return
    }
    // The window ends at the last UTC midnight, not at run time. Depot sources sync on a schedule and a
    // running job has no duration yet, so the last hours before the run are incomplete. Whole UTC days
    // also match the days on Depot's usage page, so a reader can check the figures there.
    const weekEnd = new Date()
    weekEnd.setUTCHours(0, 0, 0, 0)
    const weekStart = new Date(weekEnd.getTime() - WEEK_MS)
    const [overview, weeks] = await Promise.all([
        // Every figure comes with its value for the 7 days before date_from, so one call covers both weeks.
        apiWithRetry('repo_overview', {
            date_from: weekStart.toISOString(),
            date_to: weekEnd.toISOString(),
            include_series: 'false',
            source_id: SOURCE_ID,
            repo: GITHUB_REPOSITORY,
        }),
        readSpend(weekStart, weekEnd),
    ])
    const rows = tableRows(overview, weeks)
    if (rows.length === 0) {
        // Fail the job so the breakage is visible instead of posting an empty table.
        throw new Error('No figures to post. Check the GitHub and Depot sources and DEPOT_TOKEN.')
    }
    const blocks = buildBlocks(weekStart, weekEnd, rows, spendNotes(weeks, weekEnd))
    if (DRY_RUN) {
        console.info(JSON.stringify(blocks, null, 2))
        return
    }
    if (!SLACK_BOT_TOKEN) {
        throw new Error('SLACK_BOT_TOKEN not set on a run that should post.')
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
