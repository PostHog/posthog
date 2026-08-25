// Weekly slow-test report, posted to #flakey-tests on Monday.
//
// Sibling of weekly-flaky-report.mjs: one HogQL read of the passing test spans the
// CI timing reporter (.github/scripts/report_test_timings.py) already ships, ranked by
// median wall time, with owner attribution through tools/owners and recent editors
// resolved through the GitHub commits API into Slack mentions. The report nudges the
// people best placed to speed a test up; it does not re-derive any span signal.
//
//   GHA cron ──> HogQL over posthog.trace_spans + GitHub commits API ──> Slack
//
// Known data gap: frontend CI emits failing jest spans only (--signals-only), so the
// table is pytest-only until that emitter reports slow passing tests too.

import { pathToFileURL } from 'node:url'

import {
    API_KEY,
    cell,
    DRY_RUN,
    editWorkflowBlock,
    GITHUB_REPOSITORY,
    GITHUB_SERVER_URL,
    hogql,
    linkedCell,
    postToSlack,
    PROJECT_ID,
    repoPathResolver,
    resolveOwners,
    shortName,
    SLACK_BOT_TOKEN,
    GITHUB_REF_NAME,
} from './weekly-report-common.mjs'

const GITHUB_TOKEN = process.env.GITHUB_TOKEN || ''
const GITHUB_API_URL = process.env.GITHUB_API_URL || 'https://api.github.com'

const TOP_N = 10
const CANDIDATE_POOL = 30
const MIN_BUILDS = 3
const MAX_EDITORS = 2

// Passing tests only: failures belong to the flaky report. Master pushes and merge-queue
// gate runs are the landed-code population; PR runs add noise from code that may never
// land. One test can run in several matrix legs per build, so builds counts runs, not legs.
const SLOW_TESTS_QUERY = `
    SELECT
        if(attributes['test.runner'] = 'jest' OR service_name = 'ci-frontend', 'jest', 'pytest') AS runner,
        attributes['test.selector'] AS selector,
        any(attributes['test.file']) AS file,
        round(median(toFloat64(duration_nano)) / 1000000000, 1) AS p50_seconds,
        round(max(toFloat64(duration_nano)) / 1000000000, 1) AS max_seconds,
        uniq(resource_attributes['ci.run_id']) AS builds
    FROM posthog.trace_spans
    WHERE service_name IN {service_names}
        AND attributes['test.outcome'] = 'passed'
        AND attributes['test.selector'] != ''
        AND attributes['test.file'] != ''
        AND (resource_attributes['ci.branch'] = {for_branch} OR resource_attributes['ci.branch'] LIKE {merge_queue_glob})
        AND lower(resource_attributes['ci.repository']) = lower({repository})
        AND timestamp >= now() - INTERVAL 7 DAY
    GROUP BY runner, selector
    HAVING builds >= {min_builds}
    ORDER BY p50_seconds DESC
    LIMIT ${CANDIDATE_POOL}`

const SLOW_TEST_VALUES = {
    service_names: ['ci-backend', 'ci-frontend'],
    repository: GITHUB_REPOSITORY,
    for_branch: 'master',
    merge_queue_glob: 'trunk-merge/%',
    min_builds: MIN_BUILDS,
}

async function fetchSlowTests(runHogql = hogql) {
    const result = await runHogql(SLOW_TESTS_QUERY, SLOW_TEST_VALUES)
    return (result.results || []).map(([runner, selector, file, p50Seconds, maxSeconds, builds]) => ({
        runner,
        selector,
        file,
        p50_seconds: Number(p50Seconds),
        max_seconds: Number(maxSeconds),
        builds: Number(builds),
    }))
}

// A test whose file is not in the master checkout was added on a branch or deleted
// mid-week; in neither case is there a file to link or an editor to find.
function selectReportCandidates(items, toRepoPaths = repoPathResolver()) {
    const onMaster = []
    const dropped = []
    for (const item of items) {
        const repoPaths = toRepoPaths(item.file)
        if (repoPaths.length > 0) {
            onMaster.push({ ...item, repoPaths })
        } else {
            dropped.push(item)
        }
    }
    if (dropped.length > 0) {
        console.info(
            `dropped ${dropped.length} test(s) with no file in the checkout: ${dropped
                .map((item) => item.selector)
                .join(', ')}`
        )
    }
    return onMaster.slice(0, CANDIDATE_POOL)
}

function rankReportCandidates(items, limit = TOP_N) {
    return items
        .map((item, index) => ({ item, index }))
        .sort(
            (left, right) =>
                right.item.p50_seconds - left.item.p50_seconds ||
                right.item.max_seconds - left.item.max_seconds ||
                left.index - right.index
        )
        .slice(0, limit)
        .map(({ item }) => item)
}

// The newest unique human editors of a file, from the GitHub commits API response.
// Bots and anonymous commits are skipped: a dependency bump or a git-only identity is
// nobody to tag.
function buildEditors(commits) {
    const editors = []
    const seen = new Set()
    for (const commit of commits) {
        const login = commit.author?.login
        const email = commit.commit?.author?.email || null
        if (!login || login.endsWith('[bot]') || seen.has(login.toLowerCase())) {
            continue
        }
        seen.add(login.toLowerCase())
        editors.push({ login, email })
        if (editors.length >= MAX_EDITORS) {
            break
        }
    }
    return editors
}

async function defaultGithubFetch(url) {
    const res = await fetch(url, {
        headers: { Authorization: `Bearer ${GITHUB_TOKEN}`, Accept: 'application/vnd.github+json' },
        signal: AbortSignal.timeout(30_000),
    })
    const body = await res.text()
    if (!res.ok) {
        throw new Error(`GitHub ${url} -> ${res.status}: ${body.slice(0, 200)}`)
    }
    return JSON.parse(body)
}

async function buildEditorIndex(candidates, githubFetch = defaultGithubFetch) {
    const paths = [...new Set(candidates.flatMap((item) => (item.repoPaths?.length === 1 ? item.repoPaths : [])))]
    const editorIndex = new Map()
    await Promise.all(
        paths.map(async (path) => {
            const url = new URL(`${GITHUB_API_URL}/repos/${GITHUB_REPOSITORY}/commits`)
            url.searchParams.set('path', path)
            url.searchParams.set('sha', GITHUB_REF_NAME)
            url.searchParams.set('per_page', String(MAX_EDITORS + 2)) // headroom for skipped bots
            try {
                editorIndex.set(path, buildEditors(await githubFetch(url.toString())))
            } catch (err) {
                // Editors decorate the table; a lookup failure must not sink the post.
                console.warn(`recent-editor lookup failed for ${path}: ${err.message}`)
                editorIndex.set(path, [])
            }
        })
    )
    return editorIndex
}

async function defaultSlackFetch(apiPath) {
    const res = await fetch(`https://slack.com/api/${apiPath}`, {
        headers: { Authorization: `Bearer ${SLACK_BOT_TOKEN}` },
        signal: AbortSignal.timeout(30_000),
    })
    const body = await res.text()
    if (!res.ok) {
        // The path can carry a commit author's email (lookupByEmail) - keep it out of logs.
        throw new Error(`Slack ${apiPath.split('?')[0]} -> ${res.status}: ${body.slice(0, 200)}`)
    }
    return JSON.parse(body)
}

// Slack mention ids for the editors, cheapest lookup first: one directory page-march
// matches GitHub logins against each member's Slack login field (which PostHog's profile
// convention sets), then users.lookupByEmail covers the rest. Both need scopes the DevEx
// bot may not have, so every miss degrades to a plain GitHub link, never a failed post.
async function resolveSlackUsers(editors, slackFetch = defaultSlackFetch) {
    const bySlackLogin = new Map()
    let cursor = ''
    for (;;) {
        const page = await slackFetch(`users.list${cursor ? `?cursor=${encodeURIComponent(cursor)}` : ''}`)
        if (!page.ok) {
            throw new Error(`Slack users.list failed: ${page.error}`)
        }
        for (const member of page.members || []) {
            if (member.deleted) {
                continue
            }
            // `login` is a custom profile field some workspaces set to the GitHub handle; `name`
            // is Slack's built-in username. Either earns a mention if it matches a GitHub login.
            for (const slackLogin of [member.profile?.login, member.name]) {
                if (slackLogin && !bySlackLogin.has(slackLogin.toLowerCase())) {
                    bySlackLogin.set(slackLogin.toLowerCase(), member.id)
                }
            }
        }
        cursor = page.response_metadata?.next_cursor || ''
        if (!cursor) {
            break
        }
    }
    let emailLookupBroken = false
    return Promise.all(
        editors.map(async (editor) => {
            const slackId = bySlackLogin.get(editor.login.toLowerCase())
            if (slackId) {
                return { ...editor, slackId }
            }
            if (!editor.email || emailLookupBroken) {
                return { ...editor, slackId: null }
            }
            const byEmail = await slackFetch(`users.lookupByEmail?email=${encodeURIComponent(editor.email)}`)
            if (!byEmail.ok) {
                if (byEmail.error === 'missing_scope') {
                    emailLookupBroken = true
                    console.warn('Slack users.lookupByEmail missing_scope - remaining editors keep GitHub links')
                }
                return { ...editor, slackId: null }
            }
            return { ...editor, slackId: byEmail.user.id }
        })
    )
}

function buildEditorCell(editors) {
    if (editors.length === 0) {
        return cell('unknown')
    }
    const elements = editors.flatMap((editor, index) => [
        ...(index > 0 ? [{ type: 'text', text: ', ' }] : []),
        editor.slackId
            ? { type: 'user', user_id: editor.slackId }
            : { type: 'link', url: `${GITHUB_SERVER_URL}/${editor.login}`, text: `@${editor.login}` },
    ])
    return { type: 'rich_text', elements: [{ type: 'rich_text_section', elements }] }
}

function formatDurationSeconds(seconds) {
    const total = Math.round(seconds)
    if (total < 60) {
        return `${total}s`
    }
    const minutes = Math.floor(total / 60)
    const remainder = total % 60
    return `${minutes}m ${remainder}s`
}

function tableRows(items, ownerFor, editorsFor) {
    return items.map((item) => {
        const { owner, repoPath } = ownerFor(item)
        const name = shortName(item.selector)
        const testCell = repoPath
            ? linkedCell([{ url: `${GITHUB_SERVER_URL}/${GITHUB_REPOSITORY}/blob/master/${repoPath}`, text: name }])
            : cell(name)
        return [
            testCell,
            cell(formatDurationSeconds(item.p50_seconds)),
            cell(formatDurationSeconds(item.max_seconds)),
            cell(String(item.builds)),
            cell(owner.replace(/^team-/, '')),
            buildEditorCell(editorsFor(item)),
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
                text: `*Weekly slow tests - ${dateLabel}* _(passing tests on master CI, last 7 days)_`,
            },
        },
        {
            type: 'table',
            column_settings: [
                { align: 'left' },
                { align: 'right' },
                { align: 'right' },
                { align: 'right' },
                { align: 'left' },
                { align: 'left' },
            ],
            rows: [
                [cell('test'), cell('p50'), cell('max'), cell('builds'), cell('owner'), cell('last edited by')],
                ...rows,
            ],
        },
        {
            type: 'context',
            elements: [
                {
                    type: 'mrkdwn',
                    text: "p50 is the median wall time across the week's CI builds. No slow Jest rows yet: frontend CI reports failing test spans only.",
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

// Per-item recent-editor lookup for the table. Editors come from GitHub commits per file,
// then get Slack ids where the workspace directory maps the GitHub login. Every failure
// degrades to fewer mentions, never to a skipped post.
async function resolveEditorsFor(candidates) {
    if (!GITHUB_TOKEN) {
        console.warn('GITHUB_TOKEN not set - editor mentions degrade to "unknown".')
        return () => []
    }
    const editorIndex = await buildEditorIndex(candidates)
    const editors = [...new Map([...editorIndex.values()].flat().map((e) => [e.login.toLowerCase(), e])).values()]
    let slackEditors = editors
    if (SLACK_BOT_TOKEN) {
        try {
            slackEditors = await resolveSlackUsers(editors)
        } catch (err) {
            console.warn(`Slack user resolution failed - keeping GitHub links: ${err.message}`)
        }
    }
    const slackByLogin = new Map(slackEditors.map((e) => [e.login.toLowerCase(), e]))
    return (item) =>
        item.repoPaths?.length === 1
            ? (editorIndex.get(item.repoPaths[0]) || []).map((e) => slackByLogin.get(e.login.toLowerCase()))
            : []
}

async function main() {
    if (!PROJECT_ID || !API_KEY) {
        console.warn('POSTHOG_PROJECT_ID / POSTHOG_API_KEY not set - skipping report. Wire them to enable.')
        return
    }
    const now = new Date()
    // Built once so candidate filtering and owner resolution share one git ls-files.
    const toRepoPaths = repoPathResolver()
    const candidates = selectReportCandidates(await fetchSlowTests(), toRepoPaths)
    const top = rankReportCandidates(candidates)
    if (top.length === 0) {
        console.info('No slow tests above the floor this week - nothing to post.')
        return
    }
    const ownerFor = resolveOwners(top, toRepoPaths)
    const editorsFor = await resolveEditorsFor(top)
    const rows = tableRows(top, ownerFor, editorsFor)
    const blocks = buildBlocks(now, rows)
    if (DRY_RUN) {
        console.info(JSON.stringify(blocks, null, 2))
        return
    }
    if (!SLACK_BOT_TOKEN) {
        throw new Error('SLACK_BOT_TOKEN not set on a non-dry run - refusing to silently skip.')
    }
    await postToSlack(blocks, 'Weekly slow tests report')
    console.info('Posted weekly slow tests report.')
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
    main().catch((err) => {
        console.error(err)
        process.exit(1)
    })
}

export {
    buildBlocks,
    buildEditorCell,
    buildEditorIndex,
    buildEditors,
    fetchSlowTests,
    formatDurationSeconds,
    rankReportCandidates,
    resolveEditorsFor,
    resolveSlackUsers,
    selectReportCandidates,
    SLOW_TEST_VALUES,
    SLOW_TESTS_QUERY,
    tableRows,
}
