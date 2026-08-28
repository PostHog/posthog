// Weekly flaky-test report, posted to #flakey-tests on Monday.
//
// PULL model, sibling of eng-analytics-weekly-digest.mjs: reads the
// engineering_analytics flaky_tests endpoint for candidates, then one pytest-only
// HogQL read of the product's ci_failures view joined to the synced runs table for
// the rerun-rescue counts and failing-job evidence links the endpoint does not
// carry yet. The product owns the flake signal; this owns cadence, owner
// attribution, and the relay.
//
//   GHA cron ──> flaky_tests endpoint + one HogQL query ──> Slack
//
// Endpoint gaps inherited here (backend follow-ups): suites that don't ship junit
// into the span pipeline are invisible, and rerun_passed_count only flows from
// retry-enabled lanes. Master-burst breakage and branch-only tests are filtered
// out client-side.

import { pathToFileURL } from 'node:url'

import {
    AUTH_HEADERS,
    cell,
    DRY_RUN,
    editWorkflowBlock,
    GITHUB_REPOSITORY,
    GITHUB_SERVER_URL,
    hogql,
    HOST,
    linkedCell,
    postToSlack,
    PROJECT_ID,
    API_KEY,
    repoPathResolver,
    requestPosthog,
    resolveOwners,
    shortName,
    SLACK_BOT_TOKEN,
    SLACK_CHANNEL,
} from './weekly-report-common.mjs'

const SOURCE_ID = process.env.ENG_ANALYTICS_SOURCE_ID || ''
// The synced runs table name carries the warehouse source prefix, which differs per project.
const RUNS_TABLE = process.env.ENG_ANALYTICS_RUNS_TABLE || 'eng_analyticsgithub_workflow_runs'
const TRUNK_TABLE = process.env.TRUNK_QUARANTINE_TABLE || 'trunkio.quarantinedtests'

const TOP_N = 10
const CANDIDATE_POOL = 40
const CLUSTER_MIN_TESTS = 5
const REPORT_RUNNERS = ['pytest', 'jest']
const RUNNER_LABELS = { pytest: 'pytest', jest: 'Jest' }

// Two systems can suppress a failing test, and only one of them reaches the endpoint. The
// quarantine file xfails the test, so the span records 'xfailed' and the item arrives already
// marked. Trunk instead masks the job verdict and leaves a hard failure in the junit, so its
// quarantines arrive as ordinary failures and have to be read separately.
// Same two variables the CI uploaders read: uploads decide whether the synced Trunk state is
// current, masking decides whether a quarantine actually keeps a failure from failing CI.
const TRUNK_UPLOADS_ON = process.env.TRUNK_UPLOAD_ENABLED === 'true'
const TRUNK_MASKS_CI = TRUNK_UPLOADS_ON && process.env.TRUNK_QUARANTINE_ENABLED === 'true'

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

function flakyTestsUrl(runner) {
    return endpointUrl('flaky_tests', {
        date_from: '-7d',
        limit: 100,
        repo: GITHUB_REPOSITORY,
        runner,
    })
}

function fetchFlakyTests(runner) {
    return requestPosthog(flakyTestsUrl(runner), { headers: AUTH_HEADERS }, 'flaky_tests')
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

// A test with no file on master runs only on the branch that added it, so only that branch can fix
// it. The span scan is branch-agnostic by design, so the checkout is what tells the two apart.
function selectReportCandidates(items, runner, toRepoPaths) {
    const qualifying = items.filter((item) => item.runner === runner && !isMasterBurst(item))
    const onMaster = []
    const branchOnly = []
    for (const item of qualifying) {
        if (toRepoPaths(item.selector.split('::')[0]).length > 0) {
            onMaster.push(item)
        } else {
            branchOnly.push(item)
        }
    }
    if (branchOnly.length > 0) {
        // Never drop silently: a resolver that stopped matching would read as a quiet week.
        console.info(
            `${runner}: dropped ${branchOnly.length} test(s) with no file on master: ${branchOnly
                .map((item) => item.selector)
                .join(', ')}`
        )
    }
    return onMaster.slice(0, CANDIDATE_POOL)
}

async function fetchCandidatePools(runners, toRepoPaths, fetchTests = fetchFlakyTests) {
    return Promise.all(
        runners.map(async (runner) => {
            const result = await fetchTests(runner)
            return { runner, candidates: selectReportCandidates(result.items || [], runner, toRepoPaths) }
        })
    )
}

// One test carries different leading path segments depending on who named it: a product suite
// runs from its product dir, jest reports from its package root, and the endpoint reports
// repo-relative. Matching on every path suffix lets either side hold the longer prefix, which a
// fixed list of known prefixes cannot do as packages come and go. Stops above the bare filename,
// where two packages' same-named files would collide.
function selectorVariants(selector) {
    const [path, ...rest] = selector.split('::')
    const tail = rest.length > 0 ? `::${rest.join('::')}` : ''
    const segments = path.split('/')
    const variants = []
    for (let start = 0; start <= segments.length - 2; start++) {
        variants.push(segments.slice(start).join('/') + tail)
    }
    return variants.length > 0 ? variants : [selector]
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

async function enrichRunnerCandidates(runner, candidates, runHogql = hogql) {
    if (runner === 'pytest') {
        return enrich(
            candidates.filter((item) => !item.cluster_size),
            runHogql
        )
    }
    const empty = { runsRescued: null, evidence: [] }
    return () => empty
}

// Trunk keys a test by (file, classname, name) rather than by one id, and the two runners split
// the name differently: pytest hides the class inside `classname` (the file's module plus the
// class), while jest puts the whole title in `name`. Trimming the module prefix recovers the
// pytest class; jest needs no reassembly, so file and name concatenate directly.
//
// `parent` carries the runner for pytest and the file path for jest, which is what separates the
// two sets. The table has no repository column, so this cannot be repo-scoped. It does not need
// to be: a row only annotates a selector the repo-scoped endpoint already returned.
const TRUNK_QUARANTINED_QUERY = `
    SELECT concat(file, '::', if(cls = '', '', concat(cls, '::')), name) AS nodeid,
        quarantined_at
    FROM (
        SELECT file, name, quarantined_at,
            replaceAll(substring(file, 1, length(file) - 3), '/', '.') AS module,
            if({runner} = 'pytest' AND startsWith(classname, concat(module, '.')),
               replaceAll(substring(classname, length(module) + 2, length(classname)), '.', '::'),
               '') AS cls
        FROM __TRUNK_TABLE__
        WHERE if({runner} = 'pytest', parent = 'pytest', parent != 'pytest')
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
        for (const variant of selectorVariants(nodeid)) {
            byVariant.set(variant, { quarantinedAt })
        }
    }
    return (item) =>
        selectorVariants(item.selector)
            .map((variant) => byVariant.get(variant))
            .find(Boolean) || null
}

// One question for both systems: is this failure already suppressed, so the queue should not ask
// anyone to act on it? Returns null while the test still fails CI.
//
// Trunk with masking off is the one case that is marked but not suppressed: Trunk called the test
// flaky, CI still goes red on it, so it stays in the queue carrying a label.
function testStatusFor(trunkFor, masksCi = TRUNK_MASKS_CI) {
    return (item) => {
        // Both counts are seven-day aggregates and the endpoint counts a quarantined run
        // separately from a failed one, so a park that ended inside the window leaves the
        // quarantined count set while CI fails on the test again. The unquarantined failures
        // decide: with any of them the test is still red and still work.
        const quarantineFile = item.classification === 'quarantined' || item.quarantined_failed_run_count > 0
        if (quarantineFile && !item.failed_run_count) {
            return { parked: true }
        }
        const trunk = trunkFor(item)
        if (!trunk) {
            return null
        }
        return { parked: masksCi }
    }
}

// Parked tests leave the queue: a suppressed failure does not fail CI, so nobody has to act on it.
//
// Dropping them has to precede clustering. A cluster's selector is a bare file path, which can
// never match a test id, so collapsing first buries parked tests in a row that then ranks as if
// CI still failed on them.
function buildQueue(candidates, statusFor) {
    return collapseClusters(candidates.filter((item) => !statusFor(item)?.parked))
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
                runner: group[0].runner,
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

// Rescued runs first (the strongest per-test signal), clusters and the rest by volume.
function rankReportCandidates(items, extrasFor) {
    return items
        .map((item, index) => ({ item, index }))
        .sort(
            (left, right) =>
                (extrasFor(right.item).runsRescued ?? 0) - (extrasFor(left.item).runsRescued ?? 0) ||
                right.item.failed_run_count - left.item.failed_run_count ||
                left.index - right.index
        )
        .slice(0, TOP_N)
        .map(({ item }) => item)
}

async function buildRunnerReports(
    candidatePools,
    getEnrichment = enrichRunnerCandidates,
    getTrunk = fetchTrunkQuarantined
) {
    return Promise.all(
        candidatePools.map(async ({ runner, candidates }) => {
            const statusFor = testStatusFor(await getTrunk(runner))
            const queue = buildQueue(candidates, statusFor)
            const extrasFor = await getEnrichment(runner, queue)
            return { runner, candidates: rankReportCandidates(queue, extrasFor), extrasFor, statusFor }
        })
    )
}

function tableRows(items, ownerFor, extrasFor, statusFor = () => null) {
    return items.map((item) => {
        const { owner, repoPath } = ownerFor(item)
        const { runsRescued, evidence } = extrasFor(item)
        const name = item.cluster_size
            ? `${item.selector.split('/').pop()} (${item.cluster_size} tests)`
            : shortName(item.selector)
        const testCell = repoPath
            ? linkedCell([{ url: `${GITHUB_SERVER_URL}/${GITHUB_REPOSITORY}/blob/master/${repoPath}`, text: name }])
            : cell(name)
        // Anything parked has already left the table, so the only status a row can carry is
        // Trunk having flagged a test that still fails CI.
        const flagged = statusFor(item) ? ' (Trunk flagged)' : ''
        const logLinks = evidence.map(({ runId, jobId }, index) => ({
            url: `${GITHUB_SERVER_URL}/${GITHUB_REPOSITORY}/actions/runs/${runId}${jobId ? `/job/${jobId}` : ''}`,
            text: String(index + 1),
        }))
        return [
            testCell,
            cell(RUNNER_LABELS[item.runner] || item.runner),
            cell(owner.replace(/^team-/, '') + flagged),
            cell(runsRescued == null ? '-' : String(runsRescued)),
            cell(String(item.failed_run_count)),
            logLinks.length > 0 ? linkedCell(logLinks) : cell('-'),
        ]
    })
}

function buildBlocks(now, rows) {
    const dateLabel = now.toISOString().slice(0, 10)
    const blocks = [
        {
            type: 'section',
            text: {
                type: 'mrkdwn',
                text: `*Weekly flaky tests - ${dateLabel}* _(CI, last 7 days, up to ${TOP_N} per runner)_`,
            },
        },
        {
            type: 'table',
            column_settings: [
                { align: 'left' },
                { align: 'left' },
                { align: 'left' },
                { align: 'right' },
                { align: 'right' },
                { align: 'left' },
            ],
            rows: [
                [cell('test'), cell('runner'), cell('owner'), cell('rescued'), cell('fails'), cell('logs')],
                ...rows,
            ],
        },
        {
            type: 'context',
            elements: [
                {
                    type: 'mrkdwn',
                    text: 'Fix: `/fixing-flaky-tests` · Park 14 days: `hogli test:quarantine add <test id>`',
                },
            ],
        },
    ]
    const editBlock = editWorkflowBlock()
    if (editBlock) {
        blocks.push(editBlock)
    }
    return blocks
}

async function main() {
    if (!PROJECT_ID || !API_KEY) {
        console.warn('POSTHOG_PROJECT_ID / POSTHOG_API_KEY not set — skipping report. Wire them to enable.')
        return
    }
    const now = new Date()
    // Built once so the filter and the owner resolution share one git ls-files.
    const toRepoPaths = repoPathResolver()
    const runnerReports = await buildRunnerReports(await fetchCandidatePools(REPORT_RUNNERS, toRepoPaths))
    const reportCandidates = runnerReports.flatMap(({ candidates }) => candidates)
    if (reportCandidates.length === 0) {
        console.info('No qualifying flaky tests this week — nothing to post.')
        return
    }
    const ownerFor = resolveOwners(reportCandidates, toRepoPaths)
    const rows = runnerReports.flatMap(({ candidates, extrasFor, statusFor }) =>
        tableRows(candidates, ownerFor, extrasFor, statusFor)
    )
    const blocks = buildBlocks(now, rows)
    if (DRY_RUN) {
        console.info(JSON.stringify(blocks, null, 2))
        return
    }
    if (!SLACK_BOT_TOKEN) {
        throw new Error('SLACK_BOT_TOKEN not set on a non-dry run — refusing to silently skip.')
    }
    await postToSlack(blocks, 'Weekly flaky test report')
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
    buildRunnerReports,
    CLUSTER_MIN_TESTS,
    enrich,
    enrichRunnerCandidates,
    fetchCandidatePools,
    fetchTrunkQuarantined,
    flakyTestsUrl,
    REPORT_RUNNERS,
    selectReportCandidates,
    tableRows,
    testStatusFor,
}
