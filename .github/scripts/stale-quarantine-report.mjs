// Reports Trunk quarantines that outlived their flake: tests quarantined for the whole window that
// ran enough times in it without a failure. Such a test is held by an Always Quarantine override or
// by a flaky status that has not resolved. The report only lists them, because lifting a quarantine
// is the owning team's decision.
//
// The weekly flaky report cannot find these. It lists quarantined tests that failed this week.

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
    requestPosthog,
    resolveOwners,
    SLACK_BOT_TOKEN,
    SLACK_CHANNEL,
    teamLabel,
} from './weekly-report-common.mjs'

const TRUNK_API = process.env.TRUNK_API_URL || 'https://api.trunk.io/v2/tests'
const TRUNK_API_KEY = process.env.TRUNK_API_KEY || ''
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
// Slack allows 100 table rows including the header.
export const ROWS_PER_TABLE = 99
const MAX_PAGES = 50
const DAY_MS = 24 * 60 * 60 * 1000

// A test that never ran in the window cannot be shown to pass. It may be deleted, skipped or renamed,
// so it is reported apart from the tests that ran clean.
export function classifyQuarantines(tests, now = new Date()) {
    const flagged = []
    for (const test of tests) {
        const ageMs = now.getTime() - Date.parse(test.quarantinedSince)
        if (Number.isNaN(ageMs) || ageMs < WINDOW_DAYS * DAY_MS) {
            continue
        }
        const quarantinedDays = Math.floor(ageMs / DAY_MS)
        const { runCount: runs = 0, failureCount } = test.metrics ?? {}
        if (runs === 0) {
            flagged.push({ test, quarantinedDays, runs, kind: 'notRunning' })
        } else if (failureCount === 0 && runs >= MIN_RUNS) {
            flagged.push({ test, quarantinedDays, runs, kind: 'passing' })
        }
    }
    return flagged.sort((a, b) => b.quarantinedDays - a.quarantinedDays)
}

// A rejected token must fail the run: a quiet skip would look the same as nothing being stale.
const trunkGet = (url) =>
    requestPosthog(url, { headers: { Authorization: `Bearer ${TRUNK_API_KEY}` } }, 'trunk quarantine list')

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

function rowFor({ test, quarantinedDays, runs, kind, owner }, withTeam) {
    const name = test.className ? `${test.className}.${test.name}` : test.name
    const label = (test.variant ? `${name} [${test.variant}]` : name).slice(-60)
    return [
        test.url ? linkedCell([{ url: test.url, text: label }]) : cell(label),
        ...(withTeam ? [cell(teamLabel(owner))] : []),
        cell(kind === 'passing' ? 'ran clean' : 'did not run'),
        cell(`${quarantinedDays}d`),
        cell(String(runs)),
    ]
}

export const pagesOf = (items) =>
    Array.from({ length: Math.ceil(items.length / ROWS_PER_TABLE) }, (_, page) =>
        items.slice(page * ROWS_PER_TABLE, (page + 1) * ROWS_PER_TABLE)
    )

// Slack accepts one table block per message, so both kinds share a table and a message holds one page of it.
export function sections(items, { withTeam = false, intro = true } = {}) {
    if (items.length === 0) {
        return []
    }
    const columns = withTeam ? ['test', 'team', 'status'] : ['test', 'status']
    return [
        ...(intro
            ? [
                  {
                      type: 'section',
                      text: {
                          type: 'mrkdwn',
                          text: `*Quarantined for ${WINDOW_DAYS}+ days.* "ran clean": ${MIN_RUNS}+ runs and no failure, so remove the override or check why the flaky status has not resolved. "did not run": the test may be deleted, skipped or renamed.`,
                      },
                  },
              ]
            : []),
        {
            type: 'table',
            column_settings: [...columns.map(() => ({ align: 'left' })), { align: 'right' }, { align: 'right' }],
            rows: [
                [...columns.map(cell), cell('quarantined'), cell(`runs, ${WINDOW_DAYS}d`)],
                ...items.map((item) => rowFor(item, withTeam)),
            ],
        },
    ]
}

const footer = (extra = []) => ({
    type: 'context',
    elements: [{ type: 'mrkdwn', text: ['Source: Trunk Flaky Tests API', ...extra].join(' · ') }],
})

function digestBlocks(pages) {
    const editBlock = editWorkflowBlock()
    return [
        { type: 'header', text: { type: 'plain_text', text: 'Stale test quarantines' } },
        ...sections(pages[0], { withTeam: true }),
        footer(),
        ...(editBlock ? [editBlock] : []),
    ]
}

const moreNote = (rows) =>
    rows.length > ROWS_PER_TABLE
        ? [
              {
                  type: 'context',
                  elements: [
                      {
                          type: 'mrkdwn',
                          text: `${rows.length - ROWS_PER_TABLE} more not shown, see the report for all teams`,
                      },
                  ],
              },
          ]
        : []

function teamBlocks({ owner, rows }, digestUrl) {
    return [
        {
            type: 'section',
            text: { type: 'mrkdwn', text: `*Stale test quarantines owned by ${teamLabel(owner)}*` },
        },
        ...sections(rows.slice(0, ROWS_PER_TABLE)),
        ...moreNote(rows),
        footer(digestUrl ? [`<${digestUrl}|Report for all teams>`] : []),
    ]
}

const teamReport = {
    title: 'Stale test quarantines',
    rowLabel: 'tests',
    teamBlocks,
    threadSliceBlocks: (team, reason) => [
        {
            type: 'section',
            text: { type: 'mrkdwn', text: `*${teamLabel(team.owner)}* _(${reason} ${team.channel})_` },
        },
        ...sections(team.rows.slice(0, ROWS_PER_TABLE)),
        ...moreNote(team.rows),
    ],
}

async function main() {
    if (!TRUNK_API_KEY || COLLECTION_IDS.length === 0) {
        console.warn(
            'TRUNK_API_KEY or TRUNK_STALE_QUARANTINE_COLLECTION_IDS not set, skipping the stale quarantine report.'
        )
        return
    }
    const tests = (await Promise.all(COLLECTION_IDS.map((id) => fetchQuarantined(id)))).flat()
    const flagged = classifyQuarantines(tests)
    const countOf = (kind) => flagged.filter((item) => item.kind === kind).length
    console.info(
        `${tests.length} quarantined, ${countOf('passing')} passing clean, ${countOf('notRunning')} not running.`
    )
    if (flagged.length === 0) {
        return
    }
    const selectorOf = ({ test }) => ({ selector: `${test.file || ''}::${test.name}` })
    const ownerFor = resolveOwners(flagged.map(selectorOf), repoPathResolver(), OWNERS_PRODUCER)
    const owned = flagged.map((item) => ({ ...item, ...ownerFor(selectorOf(item)) }))
    const entries = owned.map((item) => ({ owner: item.owner, slack: item.slack, row: item }))
    const pages = pagesOf(owned)
    const blocks = digestBlocks(pages)
    const teamDigests = buildTeamDigests(entries)
    const withheld = TEAM_CHANNEL_POSTS ? null : 'shadow: would post to'
    if (DRY_RUN) {
        console.info(JSON.stringify(blocks, null, 2))
        console.info(`${pages.length} page(s) of up to ${ROWS_PER_TABLE} rows.`)
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
    for (const page of pages.slice(1)) {
        await postToSlack(sections(page, { withTeam: true, intro: false }), 'Stale test quarantines', {
            threadTs: digest.ts,
        })
    }
    console.info(`Posted the stale quarantine report to ${SLACK_CHANNEL}.`)
    await deliverTeamDigests(teamDigests, { digest, report: teamReport, withheld })
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
    main().catch((err) => {
        console.error(err)
        process.exit(1)
    })
}
