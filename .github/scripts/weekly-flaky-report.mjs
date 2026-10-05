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

import { readFileSync } from 'node:fs'
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
const QUARANTINE_FILE = '.test_quarantine.json'
const TRUNK_TABLE = process.env.TRUNK_QUARANTINE_TABLE || 'trunkio.quarantinedtests'

// A HogQL query without a LIMIT returns 100 rows, which is fewer than Trunk quarantines. A page
// that comes back full may be cut short, and a partial list reads as "not quarantined".
const QUERY_ROW_LIMIT = 50000
const REPORT_WINDOW_DAYS = 7
const TOP_N = 10
const CANDIDATE_POOL = 40
const CLUSTER_MIN_TESTS = 5
const REPORT_RUNNERS = ['pytest', 'jest']
const RUNNER_LABELS = { pytest: 'pytest', jest: 'Jest' }

// Two systems can suppress a failing test. The quarantine file xfails the test until its entry
// expires, so the span records 'xfailed'. A test its author marked xfail records the same outcome,
// so the file is what tells a quarantine from an expected failure. Trunk instead masks the job
// verdict and leaves a hard failure in the junit, so its quarantines arrive as ordinary failures
// and have to be read separately.
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
            LIMIT ${QUERY_ROW_LIMIT}`,
            { repository: GITHUB_REPOSITORY, selectors }
        )
        rows = result.results || []
    } catch (err) {
        // The table still works without these columns; degrade rather than skip the post.
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
    )
    LIMIT ${QUERY_ROW_LIMIT}`

// Uploads off, a missing table, or a query error all degrade to a report without Trunk state,
// never to a failed run.
async function fetchTrunkQuarantined(runner, runHogql = hogql, enabled = TRUNK_UPLOADS_ON) {
    if (!enabled) {
        return null
    }
    let rows = []
    try {
        const result = await runHogql(TRUNK_QUARANTINED_QUERY.replace('__TRUNK_TABLE__', TRUNK_TABLE), {
            runner,
        })
        rows = result.results || []
    } catch (err) {
        console.warn(`Trunk quarantine lookup failed — reporting without Trunk state: ${err.message}`)
        return null
    }
    if (rows.length >= QUERY_ROW_LIMIT) {
        console.warn(`Trunk quarantine lookup returned a full page — reporting without Trunk state`)
        return null
    }
    // Trunk keeps one row per variant of a test (one per browser, for example), and the oldest row
    // is when masking began.
    const oldestByNodeid = new Map()
    for (const [nodeid, quarantinedAt] of rows) {
        const known = oldestByNodeid.get(nodeid)
        if (!oldestByNodeid.has(nodeid) || (quarantinedAt && (!known || quarantinedAt < known))) {
            oldestByNodeid.set(nodeid, quarantinedAt)
        }
    }
    const byVariant = new Map()
    for (const [nodeid, quarantinedAt] of oldestByNodeid) {
        for (const variant of selectorVariants(nodeid)) {
            byVariant.set(variant, { quarantinedAt })
        }
    }
    return (item) =>
        selectorVariants(item.selector)
            .map((variant) => byVariant.get(variant))
            .find(Boolean) || null
}

// `product:batch-exports` stands for the path prefix `products/batch_exports/`.
function expandedQuarantineSelector(entryId) {
    return entryId.startsWith('product:')
        ? `products/${entryId.slice('product:'.length).replaceAll('-', '_')}/`
        : entryId
}

// Mirrors `selector_matches` in tools/hogli-commands/hogli_commands/quarantine/core.py: an entry
// covers a test, a class, a file, a directory, or a whole product.
function quarantineEntryCovers(entryId, selector) {
    if (entryId.startsWith('product:')) {
        return selector.startsWith(expandedQuarantineSelector(entryId))
    }
    const id = entryId.replace(/\/+$/, '')
    return selector === id || ['/', '::', '[', ' '].some((boundary) => selector.startsWith(`${id}${boundary}`))
}

// Which entry of the repository quarantine file covered a test during the report window. An entry
// suppresses the test through its `expires` date and is inert after it, so an entry that expired
// inside the window still explains the xfailed runs before that date.
//
// Returns null when the file cannot be read. No entry then means "unknown", not "not quarantined".
function loadQuarantineFile(runner, { read = () => readFileSync(QUARANTINE_FILE, 'utf8'), now = new Date() } = {}) {
    let entries
    try {
        const parsed = JSON.parse(read())
        entries = parsed.entries
        if (parsed.version !== 1 || !Array.isArray(entries)) {
            throw new Error('not a version 1 quarantine file')
        }
    } catch (err) {
        console.warn(`${QUARANTINE_FILE} is unreadable — reporting without file quarantines: ${err.message}`)
        return null
    }
    const today = now.toISOString().slice(0, 10)
    const windowStart = new Date(now.getTime() - REPORT_WINDOW_DAYS * 24 * 60 * 60 * 1000).toISOString().slice(0, 10)
    // Longest selector first, so the first match is the most specific one, as it is when CI
    // applies the file.
    const inWindow = entries
        .filter(
            (entry) =>
                (entry.runner || 'pytest') === runner && entry.id && entry.expires && entry.expires >= windowStart
        )
        .sort(
            (left, right) => expandedQuarantineSelector(right.id).length - expandedQuarantineSelector(left.id).length
        )
    return (item) => {
        const variants = selectorVariants(item.selector)
        const covering = inWindow.find((entry) => variants.some((variant) => quarantineEntryCovers(entry.id, variant)))
        return covering ? { expires: covering.expires, active: covering.expires >= today } : null
    }
}

// One question for both systems: is this failure suppressed, and for how long? Suppressed tests
// stay in the table with their suppression labeled, so masked failures remain visible.
//
// Trunk with masking off is marked but not suppressed: Trunk called the test flaky, CI still goes
// red on it, so it reads 'flagged' rather than a quarantine date.
function quarantineStatusFor(trunkFor, fileFor, masksCi = TRUNK_MASKS_CI) {
    return (item) => {
        // A cluster's bare file selector can never match a per-test quarantine, so the members'
        // statuses are counted at collapse time and the row reports how many are suppressed.
        if (item.cluster_size) {
            return item.quarantined_member_count ? `${item.quarantined_member_count}/${item.cluster_size}` : null
        }
        const fileEntry = fileFor?.(item)
        if (fileEntry) {
            return `${fileEntry.active ? 'until' : 'expired'} ${fileEntry.expires}`
        }
        const trunk = trunkFor?.(item)
        if (!trunk) {
            return null
        }
        if (!masksCi) {
            return 'flagged'
        }
        const since = (trunk.quarantinedAt || '').slice(0, 10)
        return since ? `since ${since}` : 'yes'
    }
}

// The endpoint counts an xfailed run apart from a failed one. A file quarantine xfails a test that
// fails, so its xfailed runs are failures. Without an entry the xfail marker is the author's, and a
// test that only ever xfailed did what its author expects.
function countFileQuarantinedRuns(runner, items, fileFor) {
    if (!fileFor) {
        return items
    }
    const kept = []
    const expected = []
    for (const item of items) {
        if (fileFor(item)) {
            kept.push({ ...item, failed_run_count: item.failed_run_count + item.quarantined_failed_run_count })
        } else if (item.failed_run_count || item.same_commit_recovery_run_count) {
            kept.push(item)
        } else {
            expected.push(item)
        }
    }
    if (expected.length > 0) {
        console.info(
            `${runner}: dropped ${expected.length} test(s) that only failed as expected (xfail): ${expected
                .map((item) => item.selector)
                .join(', ')}`
        )
    }
    return kept
}

// 5+ co-failing tests in one file are one shared-fixture incident, not N flakes.
function collapseClusters(items, statusFor) {
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
                quarantined_member_count: group.filter((item) => {
                    const status = statusFor(item)
                    return status && status !== 'flagged'
                }).length,
                // Members fail in the same runs and on the same PRs, so the max is the provable floor
                // rather than a sum.
                failed_run_count: largest('failed_run_count'),
                same_commit_recovery_run_count: largest('same_commit_recovery_run_count'),
                failed_pr_count: largest('failed_pr_count'),
                quarantined_failed_run_count: 0,
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

// Failures with no recovery prove no flake. A quarantine is the other proof that a test is known
// to fail, so those stay. The endpoint classification cannot decide this, because it also reads an
// xfail marker that the test author wrote as a quarantine.
function isKnownFlake(item, trunkFor, fileFor) {
    if (item.same_commit_recovery_run_count > 0 || trunkFor(item)) {
        return true
    }
    return fileFor ? Boolean(fileFor(item)) : item.quarantined_failed_run_count > 0
}

async function buildRunnerReports(
    candidatePools,
    getEnrichment = enrichRunnerCandidates,
    getTrunk = fetchTrunkQuarantined,
    getQuarantineFile = loadQuarantineFile
) {
    return Promise.all(
        candidatePools.map(async ({ runner, candidates }) => {
            const trunkFor = await getTrunk(runner)
            const fileFor = getQuarantineFile(runner)
            const statusFor = quarantineStatusFor(trunkFor, fileFor)
            const knownFlakes = trunkFor
                ? candidates.filter((item) => isKnownFlake(item, trunkFor, fileFor))
                : candidates
            // The endpoint ranks an xfailed run below a failed one, so the pool is cut after the
            // file-quarantined runs are counted.
            const counted = rankByReportedCounts(countFileQuarantinedRuns(runner, knownFlakes, fileFor))
            const queue = collapseClusters(counted.slice(0, CANDIDATE_POOL), statusFor)
            const extrasFor = await getEnrichment(runner, queue)
            return { runner, candidates: rankByReportedCounts(queue).slice(0, TOP_N), extrasFor, statusFor }
        })
    )
}

function tableRows(items, ownerFor, extrasFor, statusFor = () => null) {
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
                '*Quarantine* shows when masking started (since), when it ends (until), or when it ended (expired). A quarantine hides the failure, so the test still needs a fix.',
                'A count with a + covers several tests in one file and is a minimum.',
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
    const entries = runnerReports.flatMap(({ candidates, extrasFor, statusFor }) => {
        const reportRows = tableRows(candidates, ownerFor, extrasFor, statusFor)
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
    loadQuarantineFile,
    quarantineStatusFor,
    REPORT_RUNNERS,
    selectReportCandidates,
    tableRows,
}
