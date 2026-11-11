// Weekly CI digest for #alerts-devex. It compares the last 7 complete UTC days with the 7 days before.
// Spend covers every repository in the organization. Runner, Depot CI and container build minutes come
// from Depot's usage API. Cache storage is not counted in weekly spend. The contract line starts from
// Depot's credit balance, which is current as of the last invoice, and subtracts this month's usage.
// PR workflow p95 durations come from the workflow_health endpoint, which computes them over
// successful pull request runs only.

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
// 'owner/repo/.github/workflows/x.yml@refs/heads/master'. Actions sets it, so the edit link survives a rename.
const GITHUB_WORKFLOW_REF = process.env.GITHUB_WORKFLOW_REF || ''
const GITHUB_REF_NAME = process.env.GITHUB_REF_NAME || 'master'

const DEPOT_TOKEN = process.env.DEPOT_TOKEN || ''
const DEPOT_CONTRACT_USD = Number(process.env.DEPOT_CONTRACT_USD || 0)
const DEPOT_CONTRACT_START = process.env.DEPOT_CONTRACT_START || ''
const DEPOT_CONTRACT_END = process.env.DEPOT_CONTRACT_END || ''

const RUNNER_USD_PER_MINUTE = 0.004
const BUILD_USD_PER_MINUTE = 0.04
// Depot bills Depot CI in raw vCPU-minutes, while runner minutes are 2-vCPU-equivalent, so the two
// rates are not comparable. Keep this equal to DEPOT_CI_RATE_USD_PER_VCPU_SECOND × 60 in
// products/engineering_analytics/backend/logic/cost.py, so the digest and the app agree.
const DEPOT_CI_USD_PER_VCPU_MINUTE = 0.003

const DAY_MS = 24 * 60 * 60 * 1000
const WEEK_MS = 7 * DAY_MS

// Keep this, plus one day's retries, inside the job's timeout-minutes.
const DEPOT_TIME_BUDGET_MS = 20 * 60 * 1000
const STARTED_AT = performance.now()

const PR_DURATION_BUDGET_SECONDS = 20 * 60
// One slow run can move the p95 of a workflow with few runs in the week by minutes.
const MIN_PERCENTILE_RUNS = 100
// Slack rejects a message with a section text over 3,000 characters.
const SLACK_SECTION_MAX_CHARS = 3000

function billedMinutes(minutes) {
    // Protobuf JSON omits a field at its zero default.
    const value = minutes ?? 0
    if (!Number.isFinite(value) || value < 0) {
        throw new Error('Depot GetUsage returned invalid billed minutes')
    }
    return value
}

async function depotUsageSpend(startAt, endAt) {
    // Error messages are fixed text, because they reach the public Actions log and Depot's responses
    // carry billing data.
    const res = await fetch('https://api.depot.dev/depot.core.v1.UsageService/GetUsage', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'Connect-Protocol-Version': '1',
            Authorization: `Bearer ${DEPOT_TOKEN}`,
        },
        body: JSON.stringify({ startAt: startAt.toISOString(), endAt: endAt.toISOString() }),
        signal: AbortSignal.timeout(30_000),
    }).catch(() => null)
    if (!res?.ok) {
        throw Object.assign(new Error(`Depot GetUsage failed${res ? ` with ${res.status}` : ''}`), {
            retryable: !res || res.status >= 500 || res.status === 429,
        })
    }
    const usage = await res.json().catch(() => null)
    const jobs = usage?.githubActionsJobs ?? []
    const ciWorkflows = usage?.depotCi ?? []
    const builds = usage?.containerBuild ?? []
    if (
        !usage ||
        typeof usage !== 'object' ||
        !Array.isArray(jobs) ||
        !Array.isArray(ciWorkflows) ||
        !Array.isArray(builds)
    ) {
        throw new Error('Depot GetUsage returned invalid usage')
    }
    const byRepository = (entries, usd) => {
        let all = 0
        let here = 0
        for (const entry of entries) {
            const amount = usd(entry)
            all += amount
            if (isThisRepository(entry?.repo)) {
                here += amount
            }
        }
        return [all, here]
    }
    const [runners, repoRunners] = byRepository(
        jobs,
        (repo) => billedMinutes(repo?.total?.minutesBilled) * RUNNER_USD_PER_MINUTE
    )
    const [depotCi, repoDepotCi] = byRepository(
        ciWorkflows,
        (workflow) => billedMinutes(workflow?.vcpuMinutesBilled) * DEPOT_CI_USD_PER_VCPU_MINUTE
    )
    const containerBuilds = builds.reduce(
        (sum, project) => sum + billedMinutes(project?.minutesBilled) * BUILD_USD_PER_MINUTE,
        0
    )
    return { runners, repoRunners, depotCi, repoDepotCi, containerBuilds }
}

function isThisRepository(name) {
    return typeof name === 'string' && name.toLowerCase() === GITHUB_REPOSITORY.toLowerCase()
}

// GetUsage runs out of processing time on a week of our Depot CI usage and answers 500 or 429, so
// every read asks for one UTC day at a time. Past the time budget, the digest posts without spend
// rather than letting the job limit stop it before it posts anything. A day is requested once per
// run and reused, because the contract's month to date overlaps the weeks.
const dayReads = new Map()

async function spend(startAt, endAt) {
    const sum = { runners: 0, repoRunners: 0, depotCi: 0, repoDepotCi: 0, containerBuilds: 0 }
    for (const [from, to] of utcDays(startAt, endAt)) {
        const range = `${from.toISOString()}/${to.toISOString()}`
        if (!dayReads.has(range)) {
            if (performance.now() - STARTED_AT > DEPOT_TIME_BUDGET_MS) {
                throw new Error('Depot GetUsage reads ran past their time budget')
            }
            dayReads.set(range, withRetry(() => depotUsageSpend(from, to)))
        }
        const day = await dayReads.get(range)
        for (const key of Object.keys(sum)) {
            sum[key] += day[key]
        }
    }
    return { ...sum, total: sum.runners + sum.depotCi + sum.containerBuilds }
}

function* utcDays(startAt, endAt) {
    for (let from = startAt; from < endAt; ) {
        const to = new Date(Math.min(from.getTime() + DAY_MS, endAt.getTime()))
        yield [from, to]
        from = to
    }
}

async function depotCreditBalanceUsd() {
    const res = await fetch('https://api.depot.dev/depot.core.v1.CreditService/GetCreditBalance', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'Connect-Protocol-Version': '1',
            Authorization: `Bearer ${DEPOT_TOKEN}`,
        },
        body: '{}',
        signal: AbortSignal.timeout(30_000),
    }).catch(() => null)
    if (!res?.ok) {
        throw Object.assign(new Error(`Depot GetCreditBalance failed${res ? ` with ${res.status}` : ''}`), {
            retryable: !res || res.status >= 500,
        })
    }
    const balance = await res.json().catch(() => null)
    const minor = balance?.remainingCreditMinor
    if (balance?.currency !== 'USD' || typeof minor !== 'string' || !/^\d+$/.test(minor)) {
        throw new Error('Depot GetCreditBalance returned an invalid balance')
    }
    return Number(minor) / 100
}

async function contractUsed(weekEnd) {
    const balance = await withRetry(depotCreditBalanceUsd)
    const monthStart = new Date(Date.UTC(weekEnd.getUTCFullYear(), weekEnd.getUTCMonth(), 1))
    const monthToDate = await spend(monthStart, weekEnd)
    return DEPOT_CONTRACT_USD - (balance - monthToDate.total)
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

function unavailable(what) {
    return (err) => {
        console.warn(`${what} unavailable: ${err.message}. Posting without it.`)
        return null
    }
}

// Null when either week cannot be read, because a partial total would mislead.
async function readSpend(weekStart, weekEnd) {
    if (!DEPOT_TOKEN) {
        console.warn('DEPOT_TOKEN not set. Posting without spend.')
        return null
    }
    const contract = contractDates(weekEnd)
    if (!contract) {
        console.warn('Depot contract variables missing or invalid. Posting without the contract sentence.')
    }
    const lastWeek = await spend(weekStart, weekEnd).catch(unavailable('Spend'))
    const priorWeek =
        lastWeek && (await spend(new Date(weekStart.getTime() - WEEK_MS), weekStart).catch(unavailable('Spend')))
    if (!priorWeek) {
        return null
    }
    const used = contract && (await contractUsed(weekEnd).catch(unavailable('Contract spend')))
    return { lastWeek, priorWeek, contract: used == null ? null : { ...contract, used } }
}

function prWorkflowHealth(dateFrom, dateTo) {
    return withRetry(() =>
        api('workflow_health', {
            date_from: dateFrom.toISOString(),
            date_to: dateTo.toISOString(),
            run_scope: 'pull_request',
            source_id: SOURCE_ID,
            repo: GITHUB_REPOSITORY,
        })
    )
}

// PR workflows whose p95 is over the budget, slowest first. Null when either week cannot be read.
async function readSlowWorkflows(weekStart, weekEnd) {
    return Promise.all([
        prWorkflowHealth(weekStart, weekEnd),
        prWorkflowHealth(new Date(weekStart.getTime() - WEEK_MS), weekStart),
    ])
        .then(([lastWeek, priorWeek]) => {
            const priorP95 = new Map(priorWeek.map((w) => [w.workflow_name, w.p95_seconds]))
            return lastWeek
                .filter(
                    (w) => w.percentile_run_count >= MIN_PERCENTILE_RUNS && w.p95_seconds > PR_DURATION_BUDGET_SECONDS
                )
                .sort((a, b) => b.p95_seconds - a.p95_seconds)
                .map((w) => ({
                    name: w.workflow_name,
                    url: workflowRunsUrl(w.repo, w.workflow_name),
                    p95: w.p95_seconds,
                    priorP95: priorP95.get(w.workflow_name),
                }))
        })
        .catch(unavailable('PR workflow durations'))
}

function workflowRunsUrl(repo, workflowName) {
    const path = [repo.owner, repo.name, 'actions', 'workflows', workflowName].map(encodeURIComponent).join('/')
    return `${HOST}/project/${PROJECT_ID}/engineering-analytics/repos/${path}`
}

function slackEscape(text) {
    return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

function splitIntoSections(lines) {
    const notes = []
    for (const line of lines) {
        const last = notes.at(-1)
        if (last != null && last.length + 1 + line.length <= SLACK_SECTION_MAX_CHARS) {
            notes[notes.length - 1] = `${last}\n${line}`
        } else {
            notes.push(line)
        }
    }
    return notes
}

function slowWorkflowNotes(slow) {
    if (slow == null) {
        return []
    }
    const budget = fmtLongDuration(PR_DURATION_BUDGET_SECONDS)
    if (slow.length === 0) {
        return [`Every PR workflow had a p95 under ${budget}.`]
    }
    const lines = slow.map(({ name, url, p95, priorP95 }) => {
        const prior = priorP95 ? ` (${fmtLongDuration(priorP95)} the week before)` : ''
        return `• <${url}|${slackEscape(name)}>: ${fmtLongDuration(p95)}${prior}`
    })
    return splitIntoSections([`*PR workflows with a p95 over ${budget}*`, ...lines])
}

function isoDay(date) {
    return date.toISOString().slice(0, 10)
}

function contractSummary(contract, weeklySpend, weekEnd) {
    const used = `Depot contract: ${fmtUsd(contract.used)} of ${fmtUsd(DEPOT_CONTRACT_USD)} used through ${isoDay(new Date(weekEnd.getTime() - DAY_MS))}, not counting this month's cache storage.`
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
    // Catches a hung connection. Every retry together stays inside the job's timeout-minutes.
    const res = await fetch(url, {
        headers: { Authorization: `Bearer ${API_KEY}` },
        signal: AbortSignal.timeout(150_000),
    })
    // A 4xx is a configuration error that a retry cannot fix.
    const retryable = res.ok || res.status >= 500 || res.status === 429
    const fail = (detail) => {
        throw Object.assign(new Error(`${action} -> ${res.status}: ${detail}`), { retryable })
    }
    // The message never quotes the body, because it reaches the public Actions log.
    const parsed = await res.json().catch(() => fail('non-JSON response'))
    if (!res.ok) {
        fail(typeof parsed?.detail === 'string' ? parsed.detail : 'request failed')
    }
    return parsed
}

const RETRY_ATTEMPTS = 3
const RETRY_DELAY_MS = 30_000

// A busy ClickHouse cluster can push one attempt past the API gateway's timeout, and Depot's API
// returns an occasional 503.
async function withRetry(call) {
    for (let attempt = 1; ; attempt++) {
        try {
            return await call()
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

// Null when either week lacks the metric, so a source that is not synced yet gives a shorter table.
function compare(metric, current, previous, format) {
    if (current == null || previous == null) {
        return null
    }
    return [metric, format(current), format(previous), fmtDelta(current, previous)]
}

function spendRows({ lastWeek: last, priorWeek: prior }, overview) {
    const perPr = (week, merges) => (merges ? (week.repoRunners + week.repoDepotCi) / merges : null)
    return [
        compare('Depot spend', last.total, prior.total, fmtUsd),
        compare('└ runners', last.runners, prior.runners, fmtUsd),
        compare('└ Depot CI', last.depotCi, prior.depotCi, fmtUsd),
        compare('└ container builds', last.containerBuilds, prior.containerBuilds, fmtUsd),
        compare(
            '$ / merged PR',
            perPr(last, overview.merged_pr_count),
            perPr(prior, overview.merged_pr_count_prev),
            fmtUsd
        ),
    ].filter(Boolean)
}

function tableRows(overview, weeks) {
    const spend = weeks ? spendRows(weeks, overview) : []
    // Both weeks need ready→merge to compare like with like. Otherwise the row shows open→merge.
    const ready = overview.median_ready_to_merge_seconds != null && overview.median_ready_to_merge_seconds_prev != null
    return [
        // Actions logs are public, so a dry run prints no spend.
        ...(DRY_RUN ? spend.map(([metric]) => [metric, HIDDEN, HIDDEN, HIDDEN]) : spend),
        compare('merged PRs', overview.merged_pr_count, overview.merged_pr_count_prev, fmtInt),
        compare(
            ready ? 'ready→merge median' : 'open→merge median',
            ready ? overview.median_ready_to_merge_seconds : overview.median_open_to_merge_seconds,
            ready ? overview.median_ready_to_merge_seconds_prev : overview.median_open_to_merge_seconds_prev,
            fmtLongDuration
        ),
    ]
        .filter(Boolean)
        .map((row) => row.map(cell))
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
            rows: [[cell('metric'), cell('last week'), cell('week before'), cell('change')], ...rows],
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
    if (!weeks?.contract) {
        return []
    }
    return [
        DRY_RUN ? `Depot contract sentence ${HIDDEN}.` : contractSummary(weeks.contract, weeks.lastWeek.total, weekEnd),
    ]
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
    // The window ends at the last UTC midnight. Depot sources sync on a schedule and a running job has
    // no duration yet, so the hours before the run are incomplete. Whole UTC days also match Depot's
    // usage page, so a reader can check the figures there.
    const weekEnd = new Date()
    weekEnd.setUTCHours(0, 0, 0, 0)
    const weekStart = new Date(weekEnd.getTime() - WEEK_MS)
    const [overview, weeks, slowWorkflows] = await Promise.all([
        // Every figure carries its value for the 7 days before date_from, so one call covers both weeks.
        withRetry(() =>
            api('repo_overview', {
                date_from: weekStart.toISOString(),
                date_to: weekEnd.toISOString(),
                include_series: 'false',
                source_id: SOURCE_ID,
                repo: GITHUB_REPOSITORY,
            })
        ),
        readSpend(weekStart, weekEnd),
        readSlowWorkflows(weekStart, weekEnd),
    ])
    const rows = tableRows(overview, weeks)
    if (rows.length === 0) {
        throw new Error('No figures to post. Check the GitHub and Depot sources and DEPOT_TOKEN.')
    }
    const notes = [...spendNotes(weeks, weekEnd), ...slowWorkflowNotes(slowWorkflows)]
    const blocks = buildBlocks(weekStart, weekEnd, rows, notes)
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
