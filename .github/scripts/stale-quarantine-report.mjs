// Reports Trunk quarantines that outlived their flake: tests quarantined for the whole window
// that ran enough times in it without a single failure. Trunk lifts an auto-quarantine when the
// test's status returns to healthy, so a test listed here is held by an Always Quarantine override
// or by a flaky monitor that never resolves. The report only lists. It never changes a quarantine,
// because the fix is a decision for the owning team.
//
// The weekly flaky report cannot find these: it lists quarantined tests that failed this week, and
// a stale quarantine is one that did not.

import { pathToFileURL } from 'node:url'

import {
    buildTeamDigests,
    cell,
    deliverTeamDigests,
    DRY_RUN,
    editWorkflowBlock,
    linkedCell,
    postToSlack,
    repoPathResolver,
    resolveOwners,
    SLACK_BOT_TOKEN,
    SLACK_CHANNEL,
    teamLabel,
} from './weekly-report-common.mjs'

const TRUNK_API = process.env.TRUNK_API_URL || 'https://api.trunk.io/v2/tests'
const TRUNK_API_TOKEN = process.env.TRUNK_API_TOKEN || ''
const COLLECTION_IDS = (process.env.TRUNK_STALE_QUARANTINE_COLLECTION_IDS || '')
    .split(',')
    .map((id) => id.trim())
    .filter(Boolean)
const TEAM_CHANNEL_POSTS = process.env.STALE_QUARANTINE_TEAM_CHANNELS === 'true'
const OWNERS_PRODUCER = 'stale_quarantine'

// Trunk accepts 1d, 7d, 14d and 30d. The quarantine has to be older than the window, so a test
// quarantined last week cannot be called stale on a 14 day look.
export const WINDOW_DAYS = 14
// Fewer runs prove little: a test that ran twice and passed twice has not shown it stopped flaking.
export const MIN_RUNS = 20
const PAGE_LIMIT = 100
const MAX_PAGES = 50
const DAY_MS = 24 * 60 * 60 * 1000

// A test that never ran in the window cannot be shown to pass. It may be deleted, skipped or renamed,
// so it is reported apart from the tests that ran clean.
export function classifyQuarantines(tests, now = new Date(), { windowDays = WINDOW_DAYS, minRuns = MIN_RUNS } = {}) {
    const passing = []
    const notRunning = []
    for (const test of tests) {
        const since = Date.parse(test.quarantinedSince)
        if (Number.isNaN(since) || now.getTime() - since < windowDays * DAY_MS) {
            continue
        }
        const quarantinedDays = Math.floor((now.getTime() - since) / DAY_MS)
        const runs = test.metrics?.runCount ?? 0
        if (runs === 0) {
            notRunning.push({ test, quarantinedDays, runs })
        } else if (test.metrics.failureCount === 0 && runs >= minRuns) {
            passing.push({ test, quarantinedDays, runs })
        }
    }
    const oldestFirst = (a, b) => b.quarantinedDays - a.quarantinedDays
    return { passing: passing.sort(oldestFirst), notRunning: notRunning.sort(oldestFirst) }
}

async function trunkGet(url, attempts = 3) {
    for (let attempt = 1; ; attempt++) {
        const res = await fetch(url, { headers: { Authorization: `Bearer ${TRUNK_API_TOKEN}` } })
        if (res.ok) {
            return res.json()
        }
        // A rejected token must fail the run: a quiet skip would look the same as nothing being stale.
        const retryable = res.status === 429 || res.status >= 500
        if (!retryable || attempt >= attempts) {
            throw new Error(
                `Trunk ${new URL(url).pathname} answered ${res.status}: ${(await res.text()).slice(0, 200)}`
            )
        }
        await new Promise((resolve) => setTimeout(resolve, 2000 * attempt))
    }
}

export async function fetchQuarantined(collectionId, get = trunkGet) {
    const tests = []
    let cursor = null
    for (let page = 0; page < MAX_PAGES; page++) {
        const url = new URL(TRUNK_API)
        url.searchParams.set('testCollectionId', collectionId)
        url.searchParams.set('quarantineState', 'quarantined')
        url.searchParams.set('include', 'metrics')
        url.searchParams.set('period', `${WINDOW_DAYS}d`)
        url.searchParams.set('limit', String(PAGE_LIMIT))
        if (cursor) {
            url.searchParams.set('cursor', cursor)
        }
        const body = await get(url.toString())
        tests.push(...body.data)
        if (!body.hasMore) {
            return tests
        }
        cursor = body.nextCursor
    }
    // A cut-off list would read as "everything else is fine".
    throw new Error(`Trunk quarantine list for ${collectionId} exceeded ${MAX_PAGES} pages`)
}

function rowFor({ test, quarantinedDays, runs }) {
    const name = test.className ? `${test.className}.${test.name}` : test.name
    const label = test.variant ? `${name} [${test.variant}]` : name
    return [
        test.url ? linkedCell([{ url: test.url, text: label.slice(-60) }]) : cell(label.slice(-60)),
        cell(`${quarantinedDays}d`),
        cell(String(runs)),
    ]
}

function tableBlocks(heading, rows) {
    if (rows.length === 0) {
        return []
    }
    return [
        { type: 'section', text: { type: 'mrkdwn', text: heading } },
        {
            type: 'table',
            column_settings: [{ align: 'left' }, { align: 'right' }, { align: 'right' }],
            rows: [[cell('test'), cell('quarantined'), cell(`runs, ${WINDOW_DAYS}d`)], ...rows],
        },
    ]
}

function sections({ passing, notRunning }) {
    return [
        ...tableBlocks(
            `*Quarantined, ran ${MIN_RUNS}+ times in ${WINDOW_DAYS} days with no failure.* Remove the override, or check why the flaky status has not resolved.`,
            passing
        ),
        ...tableBlocks(
            `*Quarantined, did not run in ${WINDOW_DAYS} days.* The test may be deleted, skipped or renamed.`,
            notRunning
        ),
    ]
}

const footer = (extra = []) => ({
    type: 'context',
    elements: [{ type: 'mrkdwn', text: ['Source: Trunk Flaky Tests API', ...extra].join(' · ') }],
})

function digestBlocks(groups) {
    return [
        { type: 'header', text: { type: 'plain_text', text: 'Stale test quarantines' } },
        ...sections(groups),
        footer(),
        ...(editWorkflowBlock() ? [editWorkflowBlock()] : []),
    ]
}

function teamBlocks({ owner, rows }, digestUrl) {
    return [
        {
            type: 'section',
            text: { type: 'mrkdwn', text: `*Stale test quarantines owned by ${teamLabel(owner)}*` },
        },
        ...sections(groupsFromRows(rows)),
        footer(digestUrl ? [`<${digestUrl}|Report for all teams>`] : []),
    ]
}

function groupsFromRows(rows) {
    return {
        passing: rows.filter((row) => row.kind === 'passing'),
        notRunning: rows.filter((row) => row.kind === 'notRunning'),
    }
}

const teamReport = {
    title: 'Stale test quarantines',
    rowLabel: 'tests',
    teamBlocks,
    threadSliceBlocks: (team, reason) => [
        {
            type: 'section',
            text: {
                type: 'mrkdwn',
                text: `${reason} ${team.channel}: ${team.rows.length} stale quarantine(s) for ${teamLabel(team.owner)}`,
            },
        },
    ],
}

async function main() {
    if (!TRUNK_API_TOKEN || COLLECTION_IDS.length === 0) {
        console.warn(
            'TRUNK_API_TOKEN or TRUNK_STALE_QUARANTINE_COLLECTION_IDS not set, skipping the stale quarantine report.'
        )
        return
    }
    const tests = (await Promise.all(COLLECTION_IDS.map((id) => fetchQuarantined(id)))).flat()
    const { passing, notRunning } = classifyQuarantines(tests)
    const flagged = [
        ...passing.map((item) => ({ ...item, kind: 'passing' })),
        ...notRunning.map((item) => ({ ...item, kind: 'notRunning' })),
    ]
    console.info(`${tests.length} quarantined, ${passing.length} passing clean, ${notRunning.length} not running.`)
    if (flagged.length === 0) {
        return
    }
    const ownerFor = resolveOwners(
        flagged.map(({ test }) => ({ selector: `${test.file || ''}::${test.name}` })),
        repoPathResolver(),
        OWNERS_PRODUCER
    )
    const entries = flagged.map((item) => ({
        ...ownerFor({ selector: `${item.test.file || ''}::${item.test.name}` }),
        row: Object.assign(rowFor(item), { kind: item.kind }),
    }))
    const blocks = digestBlocks(groupsFromRows(entries.map(({ row }) => row)))
    const teamDigests = buildTeamDigests(entries)
    const withheld = TEAM_CHANNEL_POSTS ? null : 'shadow: would post to'
    if (DRY_RUN) {
        console.info(JSON.stringify(blocks, null, 2))
        console.info(
            JSON.stringify(
                teamDigests.map((team) => teamBlocks(team, null)),
                null,
                2
            )
        )
        return
    }
    if (!SLACK_BOT_TOKEN) {
        throw new Error('SLACK_BOT_TOKEN not set on a non-dry run, refusing to skip silently.')
    }
    const digest = await postToSlack(blocks, 'Stale test quarantines')
    console.info(`Posted the stale quarantine report to ${SLACK_CHANNEL}.`)
    await deliverTeamDigests(teamDigests, { digest, report: teamReport, withheld })
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
    main().catch((err) => {
        console.error(err)
        process.exit(1)
    })
}
