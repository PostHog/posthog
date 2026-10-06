// Weekly flaky-test report, posted to #flakey-tests on Monday.
//
// PULL model, sibling of eng-analytics-weekly-digest.mjs: reads the
// engineering_analytics flaky_tests endpoint for candidates and every count in the
// table, then one pytest-only HogQL read of the product's ci_failures view for the
// failing-job links the endpoint does not carry. The product owns the flake signal;
// this owns cadence, owner attribution, and the relay.
//
//   GHA cron ──> flaky_tests endpoint + one HogQL query ──> Slack
//
// Endpoint gaps inherited here (backend follow-ups): suites that don't ship junit
// into the span pipeline are invisible. Master-burst breakage and branch-only tests
// are filtered out client-side.

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

const REPORT_WINDOW_DAYS = 7
const TOP_N = 10
const CANDIDATE_POOL = 40
const CLUSTER_MIN_TESTS = 5
const REPORT_RUNNERS = ['pytest', 'jest']
const RUNNER_LABELS = { pytest: 'pytest', jest: 'Jest' }

// Trunk quarantines a test by masking the job verdict. It leaves a hard failure in the junit, so
// its quarantines arrive as ordinary failures and have to be read separately.
// Expected failures (xfail), including file quarantines, are outside this Trunk report.
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

// The endpoint sorts master failures first, so PR-only rows fill the tail of the page. The
// PR-only filter runs after the fetch, so request the endpoint maximum to leave headroom for
// confirmed flakes with no master failure that rank below those rows.
function flakyTestsUrl(runner) {
    return endpointUrl('flaky_tests', {
        date_from: `-${REPORT_WINDOW_DAYS}d`,
        limit: 200,
        repo: GITHUB_REPOSITORY,
        runner,
    })
}

function fetchFlakyTests(runner) {
    return requestPosthog(flakyTestsUrl(runner), { headers: AUTH_HEADERS }, 'flaky_tests')
}

// Xfail classification takes precedence over recovery, so use the recovery count directly.
function hasRecovery(item) {
    return item.same_commit_recovery_run_count > 0
}

// A known Trunk flake can fail repeatedly on master without a recorded recovery.
function isMasterBurst(item) {
    return (
        !item.knownFlake &&
        item.failed_run_count > 0 &&
        item.master_failed_run_count / item.failed_run_count >= 0.5 &&
        item.failed_pr_count <= 3
    )
}

// A test with no file on master runs only on the branch that added it, so only that branch can fix
// it. The span scan is branch-agnostic by design, so the checkout is what tells the two apart.
function selectReportCandidates(items, runner, toRepoPaths) {
    const qualifying = items.filter((item) => item.runner === runner)
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
    return onMaster
}

async function fetchCandidatePools(runners, toRepoPaths, fetchTests = fetchFlakyTests) {
    return Promise.all(
        runners.map(async (runner) => {
            const result = await fetchTests(runner)
            if (result.truncated) {
                // Rows past the page never reach the PR-only filter, so a full page is worth a trace.
                console.info(`${runner}: endpoint page is full at ${result.limit} rows; more tests qualified`)
            }
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

// The two most recent failing (run, job) pairs, from the product's ci_failures view. That view
// holds fewer runs than the endpoint counts, so it supplies links and never a number. A run on
// another CI engine has no page on GitHub, so only the runs GitHub synced get a link.
async function enrich(items, runHogql = hogql) {
    const bySelector = new Map()
    for (const item of items) {
        for (const variant of selectorVariants(item.selector)) {
            bySelector.set(variant, item)
        }
    }
    const selectors = [...bySelector.keys()]
    const empty = { evidence: [] }
    if (selectors.length === 0) {
        return () => empty
    }
    let rows = []
    try {
        const result = await runHogql(
            `SELECT f.test_id AS test_id,
                arraySlice(arraySort(x -> -x.1, groupUniqArray((toUnixTimestamp(f.timestamp), f.run_id, f.job_id))), 1, 6) AS recent
            FROM engineering_analytics_ci_failures f
            WHERE f.timestamp >= now() - INTERVAL ${REPORT_WINDOW_DAYS} DAY
                AND lower(f.repo) = lower({repository})
                AND f.test_id IN {selectors}
                AND (f.ci_engine = 'github_actions' OR f.ci_engine IS NULL)
                AND f.run_id IN (
                    SELECT id FROM ${RUNS_TABLE}
                    WHERE created_at >= toString(toDate(now() - INTERVAL 30 DAY))
                )
            GROUP BY f.test_id
            LIMIT ${selectors.length}`,
            { repository: GITHUB_REPOSITORY, selectors }
        )
        rows = result.results || []
    } catch (err) {
        // Counts come from the endpoint, so missing log links do not prevent the report.
        console.warn(`enrichment query failed — omitting job links: ${err.message}`)
        return () => empty
    }
    const enriched = new Map()
    for (const [testId, recent] of rows) {
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
        enriched.set(item.selector, { evidence })
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
    const empty = { evidence: [] }
    return () => empty
}

function fetchTrunkQuarantine() {
    return requestPosthog(
        endpointUrl('trunk_quarantine', { repo: GITHUB_REPOSITORY }),
        { headers: AUTH_HEADERS },
        'trunk_quarantine'
    )
}

// Trunk does not expire quarantines; the TTL is the product's repair deadline.
function trunkFixBy(quarantinedAt, ttlDays) {
    const startedAt = Date.parse(quarantinedAt)
    if (Number.isNaN(startedAt) || typeof ttlDays !== 'number' || !(ttlDays > 0)) {
        return null
    }
    return new Date(startedAt + ttlDays * 24 * 60 * 60 * 1000).toISOString().slice(0, 10)
}

// Uploads off, no synced Trunk source, a request error, or a cut-off page all degrade to a report
// without Trunk state, never to a failed run. A partial list would read as "not quarantined".
async function fetchTrunkQuarantined(runner, fetchQuarantine = fetchTrunkQuarantine, enabled = TRUNK_UPLOADS_ON) {
    if (!enabled) {
        return null
    }
    let debt
    try {
        debt = await fetchQuarantine()
    } catch (err) {
        console.warn(`Trunk quarantine lookup failed — reporting without Trunk state: ${err.message}`)
        return null
    }
    if (!debt?.available) {
        console.warn('Trunk quarantine state is not available — reporting without Trunk state')
        return null
    }
    if (debt.truncated) {
        console.warn(`Trunk quarantine lookup was cut at ${debt.limit} rows — reporting without Trunk state`)
        return null
    }
    const byVariant = new Map()
    for (const test of debt.tests || []) {
        if (test.runner !== runner) {
            continue
        }
        const entry = {
            quarantinedAt: test.quarantined_at,
            overdue: Boolean(test.overdue),
            fixBy: trunkFixBy(test.quarantined_at, debt.ttl_days),
        }
        for (const variant of selectorVariants(test.nodeid)) {
            byVariant.set(variant, entry)
        }
    }
    return (item) =>
        selectorVariants(item.selector)
            .map((variant) => byVariant.get(variant))
            .find(Boolean) || null
}

// The endpoint answers for every runner, so the runners share one request.
function sharedTrunkLookup(fetchQuarantine = fetchTrunkQuarantine, enabled = TRUNK_UPLOADS_ON) {
    let pending
    return (runner) => fetchTrunkQuarantined(runner, () => (pending ??= fetchQuarantine()), enabled)
}

// Every later step reads these facts, so no step asks Trunk on its own.
// `trunkFor` is null when Trunk state is unavailable.
function resolveFacts(candidates, trunkFor) {
    return candidates.map((item) => {
        const trunk = trunkFor?.(item) || null
        return {
            ...item,
            trunk,
            // Failures with no recovery prove no flake. A quarantine is the other proof that a test
            // is known to fail.
            knownFlake: hasRecovery(item) || Boolean(trunk),
            // The endpoint counts xfail separately; it does not distinguish its source.
            expectedFailureOnly: !item.failed_run_count && !hasRecovery(item),
        }
    })
}

// Is this failure suppressed, and for how long? Suppressed tests stay in the table with their
// suppression labeled, so masked failures remain visible.
//
// Trunk with masking off is marked but not suppressed: Trunk called the test flaky, CI still goes
// red on it, so it reads 'flagged' rather than a quarantine date.
function quarantineStatusFor(item, masksCi = TRUNK_MASKS_CI) {
    // A cluster's bare file selector can never match a per-test quarantine, so the members'
    // statuses are counted at collapse time and the row reports how many are suppressed.
    if (item.cluster_size) {
        return item.quarantined_member_count ? `${item.quarantined_member_count}/${item.cluster_size}` : null
    }
    const { trunk } = item
    if (!trunk) {
        return null
    }
    if (!masksCi) {
        return 'flagged'
    }
    if (trunk.fixBy) {
        return `${trunk.overdue ? 'overdue since' : 'fix by'} ${trunk.fixBy}`
    }
    const since = (trunk.quarantinedAt || '').slice(0, 10)
    return since ? `since ${since}` : 'yes'
}

// 5+ co-failing tests in one file are one shared-fixture incident, not N flakes.
function collapseClusters(items, masksCi) {
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
            const largest = (count) => Math.max(...group.map((item) => item[count]))
            collapsed.push({
                runner: group[0].runner,
                selector: file,
                cluster_size: group.length,
                // 'flagged' members still fail CI, so only real suppressions count toward the fraction.
                quarantined_member_count: masksCi ? group.filter((item) => item.trunk).length : 0,
                // Members fail in the same runs and on the same PRs, so the max is the provable floor
                // rather than a sum.
                failed_run_count: largest('failed_run_count'),
                same_commit_recovery_run_count: largest('same_commit_recovery_run_count'),
                failed_pr_count: largest('failed_pr_count'),
            })
        } else {
            collapsed.push(...group)
        }
    }
    return collapsed
}

// A cluster's count is a floor over members whose runs and PRs can overlap; the trailing + keeps
// it from reading as exact.
function countCell(item, count) {
    if (count == null) {
        return '-'
    }
    return item.cluster_size ? `${count}+` : String(count)
}

// Ranked on the endpoint's own counts, so the order and the numbers a reader sees agree.
function rankByReportedCounts(items) {
    return [...items].sort(
        (left, right) =>
            right.failed_run_count - left.failed_run_count ||
            right.same_commit_recovery_run_count - left.same_commit_recovery_run_count
    )
}

async function buildRunnerReports(
    candidatePools,
    getEnrichment = enrichRunnerCandidates,
    getTrunk = sharedTrunkLookup(),
    masksCi = TRUNK_MASKS_CI
) {
    return Promise.all(
        candidatePools.map(async ({ runner, candidates }) => {
            const trunkFor = await getTrunk(runner)
            const facts = resolveFacts(candidates, trunkFor)
            const expected = facts.filter((item) => item.expectedFailureOnly)
            if (expected.length > 0) {
                console.info(
                    `${runner}: dropped ${expected.length} test(s) with only expected failures (xfail): ${expected
                        .map((item) => item.selector)
                        .join(', ')}`
                )
            }
            // Without Trunk state a quarantine cannot be told from an unproven failure, so all stay.
            const knownFlakes = trunkFor ? facts.filter((item) => item.knownFlake) : facts
            const ranked = rankByReportedCounts(
                knownFlakes.filter((item) => !item.expectedFailureOnly && !isMasterBurst(item))
            )
            const queue = collapseClusters(ranked.slice(0, CANDIDATE_POOL), masksCi)
            const extrasFor = await getEnrichment(runner, queue)
            return { runner, candidates: rankByReportedCounts(queue).slice(0, TOP_N), extrasFor }
        })
    )
}

function tableRows(items, ownerFor, extrasFor, statusFor = quarantineStatusFor) {
    return items.map((item) => {
        const { owner, repoPath } = ownerFor(item)
        const { evidence } = extrasFor(item)
        const name = item.cluster_size
            ? `${item.selector.split('/').pop()} (${item.cluster_size} tests)`
            : shortName(item.selector)
        const testCell = repoPath
            ? linkedCell([{ url: `${GITHUB_SERVER_URL}/${GITHUB_REPOSITORY}/blob/master/${repoPath}`, text: name }])
            : cell(name)
        const logLinks = evidence.map(({ runId, jobId }, index) => ({
            url: `${GITHUB_SERVER_URL}/${GITHUB_REPOSITORY}/actions/runs/${runId}${jobId ? `/job/${jobId}` : ''}`,
            text: String(index + 1),
        }))
        return [
            testCell,
            cell(RUNNER_LABELS[item.runner] || item.runner),
            cell(owner.replace(/^team-/, '')),
            cell(statusFor(item) || '-'),
            cell(countCell(item, item.failed_pr_count)),
            cell(countCell(item, item.failed_run_count)),
            cell(countCell(item, item.same_commit_recovery_run_count)),
            logLinks.length > 0 ? linkedCell(logLinks) : cell('-'),
        ]
    })
}

// Shadow mode for per-team routing: the per-team slices carry the same rows as the
// channel digest, but posted as thread replies under it, labeled with the channel
// they would go to. Validates attribution and volume per team before any team
// channel receives a message. Takes [{owner, slack, row}] and groups by owner.
function buildTeamDigests(entries) {
    const byOwner = new Map()
    for (const { owner, slack, row } of entries) {
        if (owner === 'unowned' || !slack) {
            continue
        }
        if (!byOwner.has(owner)) {
            byOwner.set(owner, { owner, channel: slack, rows: [] })
        }
        byOwner.get(owner).rows.push(row)
    }
    return [...byOwner.values()].sort((a, b) => b.rows.length - a.rows.length)
}

function flakyTable(rows) {
    return {
        type: 'table',
        column_settings: [
            { align: 'left' },
            { align: 'left' },
            { align: 'left' },
            { align: 'left' },
            { align: 'right' },
            { align: 'right' },
            { align: 'right' },
            { align: 'left' },
        ],
        rows: [
            [
                cell('test'),
                cell('runner'),
                cell('owner'),
                cell('quarantine'),
                cell('PRs'),
                cell('failed runs'),
                cell('recovered runs'),
                cell('logs'),
            ],
            ...rows,
        ],
    }
}

const COLUMN_LEGEND = {
    type: 'context',
    elements: [
        {
            type: 'mrkdwn',
            text: [
                '*Failed runs* counts each CI run where the test failed, including runs that a quarantine kept green.',
                '*Recovered runs* counts each run where the same commit failed and passed the test.',
                '*Quarantine* shows the Trunk repair deadline (fix by), a missed deadline (overdue since), or the quarantine start date (since). Yes means quarantined with no date available. Quarantine continues until removed. Flagged means Trunk lists the test but CI failures are not masked. A fraction counts masked cluster members.',
                'A count with a + covers several tests in one file and is a minimum.',
                'Tests with only expected failures (xfail), including file quarantines, are omitted.',
            ].join(' '),
        },
    ],
}

function buildShadowBlocks({ owner, channel, rows }) {
    return [
        {
            type: 'section',
            text: {
                type: 'mrkdwn',
                text: `*${owner.replace(/^team-/, '')}* _(shadow: would post to ${channel})_`,
            },
        },
        flakyTable(rows),
        COLUMN_LEGEND,
    ]
}

function buildBlocks(now, rows) {
    const dateLabel = now.toISOString().slice(0, 10)
    const blocks = [
        {
            type: 'section',
            text: {
                type: 'mrkdwn',
                text: `*Weekly flaky tests - ${dateLabel}* _(CI, last ${REPORT_WINDOW_DAYS} days, up to ${TOP_N} per runner)_`,
            },
        },
        flakyTable(rows),
        COLUMN_LEGEND,
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
    // Rendered once; the channel table and the per-team slices share the same rows.
    const entries = runnerReports.flatMap(({ candidates, extrasFor }) => {
        const reportRows = tableRows(candidates, ownerFor, extrasFor)
        return candidates.map((item, index) => ({ ...ownerFor(item), row: reportRows[index] }))
    })
    const blocks = buildBlocks(
        now,
        entries.map(({ row }) => row)
    )
    const teamDigests = buildTeamDigests(entries)
    if (DRY_RUN) {
        console.info(JSON.stringify(blocks, null, 2))
        console.info(JSON.stringify(teamDigests.map(buildShadowBlocks), null, 2))
        return
    }
    if (!SLACK_BOT_TOKEN) {
        throw new Error('SLACK_BOT_TOKEN not set on a non-dry run — refusing to silently skip.')
    }
    const digestTs = await postToSlack(blocks, 'Weekly flaky test report')
    console.info(`Posted weekly flaky report to ${SLACK_CHANNEL}.`)
    let postedSlices = 0
    for (const [index, digest] of teamDigests.entries()) {
        if (index > 0) {
            // chat.postMessage allows about one message per second per channel.
            await new Promise((resolve) => setTimeout(resolve, 1100))
        }
        // A failed slice must not sink the slices behind it; the digest itself already landed.
        try {
            await postToSlack(buildShadowBlocks(digest), `Flaky tests owned by ${digest.owner}`, { threadTs: digestTs })
            postedSlices += 1
        } catch (err) {
            console.warn(`shadow digest for ${digest.owner} failed: ${err.message}`)
        }
    }
    console.info(`Posted ${postedSlices}/${teamDigests.length} shadow team digest(s) in thread.`)
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
    main().catch((err) => {
        console.error(err)
        process.exit(1)
    })
}

export {
    buildBlocks,
    buildShadowBlocks,
    buildTeamDigests,
    buildRunnerReports,
    CLUSTER_MIN_TESTS,
    enrich,
    enrichRunnerCandidates,
    fetchCandidatePools,
    fetchTrunkQuarantined,
    flakyTestsUrl,
    quarantineStatusFor,
    REPORT_RUNNERS,
    resolveFacts,
    selectReportCandidates,
    sharedTrunkLookup,
    tableRows,
}
