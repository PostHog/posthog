// Weekly flaky-test report, posted to #flakey-tests on Monday.
//
// PULL model, sibling of eng-analytics-weekly-digest.mjs: reads the
// engineering_analytics flaky_tests endpoint for candidates, then one HogQL read
// of the product's ci_failures view joined to the synced runs table for the
// rerun-rescue counts and failing-job evidence links the endpoint does not carry
// yet. The product owns the flake signal; this owns cadence, owner attribution,
// and the relay.
//
//   GHA cron ──> flaky_tests endpoint + one HogQL query ──> Slack
//
// Endpoint gaps inherited here (backend follow-ups): suites that don't ship junit
// into the span pipeline are invisible, and rerun_passed_count only flows from
// retry-enabled lanes. Master-burst breakage is filtered out client-side.

import { execFileSync } from 'node:child_process'
import { pathToFileURL } from 'node:url'

const HOST = (process.env.POSTHOG_HOST || 'https://us.posthog.com').replace(/\/$/, '')
const PROJECT_ID = process.env.POSTHOG_PROJECT_ID || ''
const API_KEY = process.env.POSTHOG_API_KEY || ''
const SOURCE_ID = process.env.ENG_ANALYTICS_SOURCE_ID || ''
// The synced runs table name carries the warehouse source prefix, which differs per project.
const RUNS_TABLE = process.env.ENG_ANALYTICS_RUNS_TABLE || 'eng_analyticsgithub_workflow_runs'
const TRUNK_TABLE = process.env.TRUNK_QUARANTINE_TABLE || 'trunkio.quarantinedtests'
const SLACK_BOT_TOKEN = process.env.SLACK_BOT_TOKEN || ''
const SLACK_CHANNEL = process.env.SLACK_CHANNEL || 'C09ADEV3AJD' // #flakey-tests
const DRY_RUN = ['1', 'true', 'yes'].includes((process.env.DRY_RUN || '').toLowerCase())

const GITHUB_SERVER_URL = process.env.GITHUB_SERVER_URL || 'https://github.com'
const GITHUB_REPOSITORY = process.env.GITHUB_REPOSITORY || 'PostHog/posthog'
const GITHUB_WORKFLOW_REF = process.env.GITHUB_WORKFLOW_REF || ''
const GITHUB_REF_NAME = process.env.GITHUB_REF_NAME || 'master'

const TOP_N = 10
const CANDIDATE_POOL = 40
const CLUSTER_MIN_TESTS = 5
const REPORT_RUNNERS = ['pytest']
const PARKED_NAMES_SHOWN = 5

// The endpoint's quarantine signal only covers `.test_quarantine.json`, where the pytest adapter
// xfails the test and the span records 'xfailed'. Trunk masks the job verdict instead, leaving a
// hard failure in the junit, so its quarantines reach the spans as plain failures.
// Same two variables the CI uploaders read: uploads decide whether the synced Trunk state is
// current, masking decides whether a quarantine actually keeps a failure from failing CI.
const TRUNK_UPLOADS_ON = process.env.TRUNK_UPLOAD_ENABLED === 'true'
const TRUNK_MASKS_CI = TRUNK_UPLOADS_ON && process.env.TRUNK_QUARANTINE_ENABLED === 'true'

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

function endpointUrl(action, params = {}) {
    const url = new URL(`${HOST}/api/projects/${PROJECT_ID}/engineering_analytics/${action}/`)
    for (const [k, v] of Object.entries(params)) {
        if (v !== undefined && v !== null && v !== '') {
            url.searchParams.set(k, v)
        }
    }
    if (SOURCE_ID) {
        url.searchParams.set('source_id', SOURCE_ID)
    }
    return url
}

const AUTH_HEADERS = { Authorization: `Bearer ${API_KEY}` }

function flakyTestsUrl(runner) {
    return endpointUrl('flaky_tests', {
        date_from: '-7d',
        limit: 100,
        repo: GITHUB_REPOSITORY,
        runner,
    })
}

function fetchFlakyTests(runner) {
    return withRetry(() => request(flakyTestsUrl(runner), { headers: AUTH_HEADERS }, 'flaky_tests'))
}

// `values` bind through HogQL's {placeholder} syntax, escaped server-side — never
// concatenate attacker-controlled test ids into the query source.
function hogql(query, values) {
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

// A same-commit recovery proves a flake, so only suppress likely one-merge bursts
// when the endpoint has no recovery proof.
function isMasterBurst(item) {
    return (
        item.classification === 'suspected_regression' &&
        item.failed_run_count > 0 &&
        item.master_failed_run_count / item.failed_run_count >= 0.5 &&
        item.failed_pr_count <= 3
    )
}

function selectReportCandidates(items, runner) {
    return items.filter((item) => item.runner === runner && !isMasterBurst(item)).slice(0, CANDIDATE_POOL)
}

async function fetchCandidatePools(runners, fetchTests = fetchFlakyTests) {
    return Promise.all(
        runners.map(async (runner) => {
            const result = await fetchTests(runner)
            return { runner, candidates: selectReportCandidates(result.items || [], runner) }
        })
    )
}

// Product suites run from their product dir, so a selector path may be repo- or
// product-relative — suffix-match the tracked index (full even under sparse checkout).
function repoPathResolver() {
    // The tracked-file list is a few MB; the 1MB execFileSync default truncates it.
    const tracked = execFileSync('git', ['ls-files', '*.py'], { encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 })
        .split('\n')
        .filter(Boolean)
    const trackedSet = new Set(tracked)
    const bySuffix = new Map()
    for (const path of tracked) {
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
function resolveOwners(items) {
    const toRepoPaths = repoPathResolver()
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
            const out = execFileSync('python3', ['-m', 'posthog_owners'], {
                encoding: 'utf8',
                input: allPaths.join('\n'),
                env: { ...process.env, PYTHONPATH: 'tools/owners' },
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
        return { owner, repoPath: paths.length === 1 ? paths[0] : null }
    }
}

// The logs view records test ids as pytest printed them, so a product suite appears
// product-relative there while the endpoint selector may be repo-relative.
function selectorVariants(selector) {
    const variants = [selector]
    const productRelative = selector.replace(/^products\/[^/]+\//, '')
    if (productRelative !== selector) {
        variants.push(productRelative)
    }
    return variants
}

// Rescue counts (failed at attempt N, run green at a later attempt) and the two most
// recent failing (run, job) pairs, from the product's ci_failures view.
async function enrich(items, runHogql = hogql) {
    const bySelector = new Map()
    for (const item of items) {
        for (const variant of selectorVariants(item.selector)) {
            bySelector.set(variant, item)
        }
    }
    const selectors = [...bySelector.keys()]
    const empty = { runsRescued: null, evidence: [] }
    if (selectors.length === 0) {
        return () => empty
    }
    let rows = []
    try {
        const result = await runHogql(
            `SELECT f.test_id AS test_id,
                uniqIf(f.run_id, r.run_attempt > f.run_attempt AND r.conclusion = 'success') AS runs_rescued,
                arraySlice(arrayReverseSort(x -> x.1, groupUniqArray(20)((toUnixTimestamp(f.timestamp), f.run_id, f.job_id))), 1, 6) AS recent
            FROM engineering_analytics_ci_failures f
            LEFT JOIN ${RUNS_TABLE} r ON r.id = f.run_id
            WHERE f.timestamp >= now() - INTERVAL 7 DAY
                AND lower(f.repo) = lower({repository})
                AND f.test_id IN {selectors}
            GROUP BY f.test_id`,
            { repository: GITHUB_REPOSITORY, selectors }
        )
        rows = result.results || []
    } catch (err) {
        // The table still works without these columns; degrade rather than skip the post.
        console.warn(`enrichment query failed — omitting rescue counts and job links: ${err.message}`)
        return () => empty
    }
    const enriched = new Map()
    for (const [testId, runsRescued, recent] of rows) {
        const item = bySelector.get(testId)
        if (!item) {
            continue
        }
        const seen = new Set()
        const evidence = []
        for (const [, runId, jobId] of [...recent].sort((a, b) => b[0] - a[0])) {
            if (seen.has(runId)) {
                continue
            }
            seen.add(runId)
            evidence.push({ runId, jobId })
            if (evidence.length === 2) {
                break
            }
        }
        enriched.set(item.selector, { runsRescued, evidence })
    }
    return (item) => enriched.get(item.selector) || empty
}

// Trunk keys a test by (file, classname, name), with the class inside `classname` rather than
// between file and name where a node id has it. `classname` is the file's module plus the class,
// so trimming the module prefix off it recovers the class and rebuilds the node id.
//
// The table carries no repository column, so this cannot be repo-scoped. It doesn't need to be:
// a row only annotates a selector the repo-scoped endpoint already returned, so another repo's
// rows would have to carry an identical node id to collide.
const TRUNK_QUARANTINED_QUERY = `
    SELECT concat(file, '::', if(cls = '', '', concat(cls, '::')), name) AS nodeid,
        quarantined_at
    FROM (
        SELECT file, name, quarantined_at,
            replaceAll(substring(file, 1, length(file) - 3), '/', '.') AS module,
            if(startsWith(classname, concat(module, '.')),
               replaceAll(substring(classname, length(module) + 2, length(classname)), '.', '::'),
               '') AS cls
        FROM __TRUNK_TABLE__
        WHERE parent = {runner}
    )`

// Uploads off, a missing table, or a query error all degrade to a report without Trunk state,
// never to a failed run or an empty table.
async function fetchTrunkQuarantined(runner, runHogql = hogql, enabled = TRUNK_UPLOADS_ON) {
    const none = () => null
    if (!enabled) {
        return none
    }
    let rows = []
    try {
        const result = await runHogql(TRUNK_QUARANTINED_QUERY.replace('__TRUNK_TABLE__', TRUNK_TABLE), {
            runner,
        })
        rows = result.results || []
    } catch (err) {
        console.warn(`Trunk quarantine lookup failed — reporting without Trunk state: ${err.message}`)
        return none
    }
    const byVariant = new Map()
    for (const [nodeid, quarantinedAt] of rows) {
        // Trunk reports repo-relative paths while a product suite's selector is product-relative,
        // so index both forms and look the selector up under both.
        for (const variant of selectorVariants(nodeid)) {
            byVariant.set(variant, { quarantinedAt })
        }
    }
    return (item) =>
        selectorVariants(item.selector)
            .map((variant) => byVariant.get(variant))
            .find(Boolean) || null
}

// Masking already stops these failures from failing CI, so they don't belong in a queue whose
// call to action is "park it". They stay listed below the table rather than dropped, so a
// long-lived auto-quarantine covering a real breakage still shows up somewhere.
function partitionParked(items, trunkFor, masksCi = TRUNK_MASKS_CI) {
    if (!masksCi) {
        return { queue: items, parked: [] }
    }
    return {
        queue: items.filter((item) => !trunkFor(item)),
        parked: items.filter((item) => trunkFor(item)).map((item) => ({ ...item, trunk: trunkFor(item) })),
    }
}

// Parking has to happen before clustering: a cluster's selector is a bare file path, which can
// never match a Trunk node id, so collapsing first buries quarantined tests in a row that then
// ranks as if CI still failed on them.
function buildQueue(candidates, trunkFor, masksCi = TRUNK_MASKS_CI) {
    const { queue, parked } = partitionParked(candidates, trunkFor, masksCi)
    return { queue: collapseClusters(queue), parked }
}

// 5+ co-failing tests in one file are one shared-fixture incident, not N flakes.
function collapseClusters(items) {
    const byFile = new Map()
    for (const item of items) {
        const file = item.selector.split('::')[0]
        if (!byFile.has(file)) {
            byFile.set(file, [])
        }
        byFile.get(file).push(item)
    }
    const collapsed = []
    for (const [file, group] of byFile) {
        if (group.length >= CLUSTER_MIN_TESTS) {
            collapsed.push({
                selector: file,
                cluster_size: group.length,
                failed_run_count: group.reduce((sum, item) => sum + item.failed_run_count, 0),
                failed_pr_count: Math.max(...group.map((item) => item.failed_pr_count)),
                quarantined_failed_run_count: 0,
            })
        } else {
            collapsed.push(...group)
        }
    }
    return collapsed
}

function cell(text) {
    return { type: 'raw_text', text }
}

function linkedCell(links) {
    const elements = links.flatMap(({ url, text }, index) => [
        ...(index > 0 ? [{ type: 'text', text: ' ' }] : []),
        { type: 'link', url, text },
    ])
    return { type: 'rich_text', elements: [{ type: 'rich_text_section', elements }] }
}

function shortName(selector) {
    const name = selector.split('::').pop()
    return name.length > 36 ? `${name.slice(0, 35)}…` : name
}

function tableRows(items, ownerFor, extrasFor, trunkFor = () => null) {
    return items.map((item) => {
        const { owner, repoPath } = ownerFor(item)
        const { runsRescued, evidence } = extrasFor(item)
        const name = item.cluster_size
            ? `${item.selector.split('/').pop()} (${item.cluster_size} tests)`
            : shortName(item.selector)
        const testCell = repoPath
            ? linkedCell([{ url: `${GITHUB_SERVER_URL}/${GITHUB_REPOSITORY}/blob/master/${repoPath}`, text: name }])
            : cell(name)
        const quarantined =
            item.classification === 'quarantined' || item.quarantined_failed_run_count > 0 ? ' (quarantined)' : ''
        // Only reachable with masking off: masking on moves these rows out of the table entirely.
        // Trunk marked the test, but CI still fails on it, so it stays ranked.
        const trunkFlagged = trunkFor(item) ? ' (Trunk flagged)' : ''
        const logLinks = evidence.map(({ runId, jobId }, index) => ({
            url: `${GITHUB_SERVER_URL}/${GITHUB_REPOSITORY}/actions/runs/${runId}${jobId ? `/job/${jobId}` : ''}`,
            text: String(index + 1),
        }))
        return [
            testCell,
            cell(owner.replace(/^team-/, '') + quarantined + trunkFlagged),
            cell(runsRescued == null ? '-' : String(runsRescued)),
            cell(String(item.failed_run_count)),
            logLinks.length > 0 ? linkedCell(logLinks) : cell('-'),
        ]
    })
}

function parkedSummary(parked) {
    const shown = parked.slice(0, PARKED_NAMES_SHOWN).map((item) => shortName(item.selector))
    const remaining = parked.length - shown.length
    const names = remaining > 0 ? `${shown.join(', ')}, and ${remaining} more` : shown.join(', ')
    const oldest = parked
        .map((item) => item.trunk?.quarantinedAt)
        .filter(Boolean)
        .sort()[0]
    const since = oldest ? ` Oldest parked ${oldest.slice(0, 10)}.` : ''
    const count = parked.length === 1 ? '1 test is' : `${parked.length} tests are`
    return `${count} quarantined in Trunk, so CI no longer fails on them: ${names}.${since} Fix them or take them out of quarantine.`
}

function buildBlocks(now, rows, parked = []) {
    const dateLabel = now.toISOString().slice(0, 10)
    // Every candidate can be parked, which leaves the parked note as the whole report.
    const heading = rows.length > 0 ? `Top ${rows.length} flaky tests` : 'Flaky tests'
    const blocks = [
        {
            type: 'section',
            text: {
                type: 'mrkdwn',
                text: `*${heading} — ${dateLabel}* _(backend CI, last 7 days)_`,
            },
        },
    ]
    if (rows.length > 0) {
        blocks.push(
            {
                type: 'table',
                column_settings: [
                    { align: 'left' },
                    { align: 'left' },
                    { align: 'right' },
                    { align: 'right' },
                    { align: 'left' },
                ],
                rows: [[cell('test'), cell('owner'), cell('rescued'), cell('fails'), cell('logs')], ...rows],
            },
            {
                type: 'context',
                elements: [
                    {
                        type: 'mrkdwn',
                        text: 'Fix: `/fixing-flaky-tests` · Park 14 days: `hogli test:quarantine add <test id>`',
                    },
                ],
            }
        )
    }
    if (parked.length > 0) {
        blocks.push({ type: 'context', elements: [{ type: 'mrkdwn', text: parkedSummary(parked) }] })
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
            text: 'Weekly flaky test report', // notification fallback
            unfurl_links: false,
        }),
    })
    const data = await res.json()
    if (!data.ok) {
        const validationDetails = Array.isArray(data.response_metadata?.messages)
            ? `: ${data.response_metadata.messages.join('; ')}`
            : ''
        throw new Error(`Slack chat.postMessage failed: ${data.error}${validationDetails}`)
    }
}

async function main() {
    if (!PROJECT_ID || !API_KEY) {
        console.warn('POSTHOG_PROJECT_ID / POSTHOG_API_KEY not set — skipping report. Wire them to enable.')
        return
    }
    const now = new Date()
    const [{ runner, candidates }] = await fetchCandidatePools(REPORT_RUNNERS)
    const trunkFor = await fetchTrunkQuarantined(runner)
    const { queue, parked } = buildQueue(candidates, trunkFor)
    const extrasFor = await enrich(queue.filter((item) => !item.cluster_size))
    // Rescued runs first (the strongest per-test signal), clusters and the rest by volume.
    const flaky = queue
        .sort(
            (a, b) =>
                (extrasFor(b).runsRescued ?? 0) - (extrasFor(a).runsRescued ?? 0) ||
                b.failed_run_count - a.failed_run_count
        )
        .slice(0, TOP_N)
    if (flaky.length === 0 && parked.length === 0) {
        console.info('No qualifying flaky tests this week — nothing to post.')
        return
    }
    const ownerFor = resolveOwners(flaky)
    const blocks = buildBlocks(now, tableRows(flaky, ownerFor, extrasFor, trunkFor), parked)
    if (DRY_RUN) {
        console.info(JSON.stringify(blocks, null, 2))
        return
    }
    if (!SLACK_BOT_TOKEN) {
        throw new Error('SLACK_BOT_TOKEN not set on a non-dry run — refusing to silently skip.')
    }
    await postToSlack(blocks)
    console.info(`Posted weekly flaky report to ${SLACK_CHANNEL}.`)
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
    main().catch((err) => {
        console.error(err)
        process.exit(1)
    })
}

export {
    buildBlocks,
    buildQueue,
    CLUSTER_MIN_TESTS,
    enrich,
    fetchCandidatePools,
    fetchTrunkQuarantined,
    flakyTestsUrl,
    REPORT_RUNNERS,
    selectReportCandidates,
    tableRows,
}
