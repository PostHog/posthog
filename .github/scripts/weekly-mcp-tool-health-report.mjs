// Weekly MCP tool health report, posted to the MCP team's channel on Monday.
//
// Sibling of weekly-flaky-report.mjs: one HogQL read of the `$mcp_tool_call` events the MCP
// server already captures, ranked by failed calls, with owner attribution through
// packages/owners-yaml. Each tool maps to the YAML file that defines it, so the team that owns
// the definition sees its own failing tools without the MCP team relaying them: each owning team
// also gets one Signals inbox report, suggested to the members of the PostHog role named after
// its GitHub team. Unowned tools stay in the Slack digest only.
//
//   GHA cron ──> HogQL over $mcp_tool_call ──> owners.yaml ──> Slack digest
//                                                         └──> Signals inbox report per team

import { execFileSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { pathToFileURL } from 'node:url'

import {
    API_KEY,
    buildTeamDigests,
    cell,
    deliverTeamDigests,
    DRY_RUN,
    editWorkflowBlock,
    GITHUB_REPOSITORY,
    hogql,
    HOST,
    postToSlack,
    PROJECT_ID,
    requestPosthog,
    resolveOwners,
    SLACK_BOT_TOKEN,
    SLACK_CHANNEL,
    teamLabel,
} from './weekly-report-common.mjs'

const TEAM_CHANNEL_POSTS = process.env.MCP_TOOL_HEALTH_TEAM_CHANNELS === 'true'
const FEEDBACK_CHANNEL = '#team-context-and-mcp'
// The name a team uses under `notifications:` in owners.yaml to redirect or silence this report.
const OWNERS_PRODUCER = 'mcp_tool_health'

// The inbox the team reports go to, and a personal API key with inbox:write, project:read,
// organization:read and organization_member:read, limited to the organization since roles and
// members are organization endpoints. The
// key's owner files every report, so they need the inbox-reports-create-mcp flag.
const SIGNALS_PROJECT_ID = process.env.SIGNALS_PROJECT_ID || ''
const SIGNALS_API_KEY = process.env.SIGNALS_API_KEY || ''
// owners.yaml names GitHub teams, and the organization's roles mostly carry the same names
// ('team-feature-flags' is 'Team Feature Flags'). These are the owners whose role is named differently.
const ROLE_FOR_TEAM = {
    'team-devex': 'Team Developer Experience',
    'team-managed-warehouse': 'Team Warehouse',
    'team-warehouse-sources': 'Team Warehouse Pipelines',
}
// The inbox report API's cap on suggested reviewers.
const MAX_SIGNAL_REVIEWERS = 10
// Each report can spend about 8.5 minutes on retries, so no team starts past this budget and the
// job's timeout-minutes leaves room for the query, one last slow report, and setup.
const SIGNALS_BUDGET_MS = 10 * 60_000

const REPORT_WINDOW_DAYS = 7
const TOP_N = 25
// A tool qualifies only past all three floors, so a handful of calls from one account never
// reads as a broken tool.
const MIN_ERRORS = 50
const MIN_ERROR_RATE_PCT = 10
const MIN_USERS = 5

const TOOL_DEFINITION_GLOBS = ['products/*/mcp/*.yaml', 'services/mcp/definitions/*.yaml']
// Tools with no YAML entry are handwritten in the MCP server. The registry maps each one to its
// source file, whose path services/mcp/src/owners.yaml can assign more narrowly than the directory.
const HANDWRITTEN_TOOL_PATH = 'services/mcp/src/tools'
const HANDWRITTEN_TOOL_REGISTRY = `${HANDWRITTEN_TOOL_PATH}/index.ts`

// Exec-mode calls name the real tool in `$mcp_exec_tool_call_name`. The bare `exec` dispatcher is
// excluded because its own rejections belong to the MCP server, not to any product tool. Error
// messages carry project ids and UUIDs in their API paths, so masking them groups one failure as
// one message.
const TOOL_HEALTH_QUERY = `
    SELECT tool, calls, errors, users, top_error
    FROM (
        SELECT
            coalesce(nullIf(toString(properties.$mcp_exec_tool_call_name), ''), toString(properties.$mcp_tool_name)) AS tool,
            count() AS calls,
            countIf(toBool(properties.$mcp_is_error)) AS errors,
            uniqIf(person_id, toBool(properties.$mcp_is_error)) AS users,
            arrayElement(topK(1)(if(toBool(properties.$mcp_is_error), replaceRegexpAll(substring(toString(properties.$mcp_error_message), 1, 160), '/[0-9a-f]{8}-[0-9a-f-]+|/[0-9]+', '/#'), NULL)), 1) AS top_error
        FROM events
        WHERE event = '$mcp_tool_call'
            AND timestamp >= now() - INTERVAL ${REPORT_WINDOW_DAYS} DAY
        GROUP BY tool
    )
    WHERE tool NOT IN ('', 'exec')
        AND errors >= {min_errors}
        AND errors * 100 >= calls * {min_error_rate_pct}
        AND users >= {min_users}
    ORDER BY errors DESC
    LIMIT ${TOP_N}`

const TOOL_HEALTH_VALUES = {
    min_errors: MIN_ERRORS,
    min_error_rate_pct: MIN_ERROR_RATE_PCT,
    min_users: MIN_USERS,
}

async function fetchFailingTools(runHogql = hogql) {
    const result = await runHogql(TOOL_HEALTH_QUERY, TOOL_HEALTH_VALUES)
    return (result.results || []).map(([tool, calls, errors, users, topError]) => ({
        tool,
        calls: Number(calls),
        errors: Number(errors),
        users: Number(users),
        topError: topError || '',
    }))
}

// Tool names are the keys directly under `tools:` and `wrappers:` in each definition file. A line
// scan keeps the script free of a YAML dependency, and the generator enforces this layout. Codegen
// registers a `confirmed_action` tool only as its `-prepare` and `-execute` pair, so analytics never
// sees the base name.
function parseToolNames(yamlText) {
    const names = []
    let section = null
    for (const line of yamlText.split('\n')) {
        const topLevel = /^([A-Za-z_]+):/.exec(line)
        if (topLevel) {
            section = topLevel[1]
            continue
        }
        const toolKey = /^ {4}([a-z0-9][a-z0-9-]*):\s*$/.exec(line)
        if (toolKey && (section === 'tools' || section === 'wrappers')) {
            names.push(toolKey[1])
        }
        if (/^ {8}confirmed_action:/.test(line) && section === 'tools' && names.length > 0) {
            const base = names.pop()
            names.push(`${base}-prepare`, `${base}-execute`)
        }
    }
    return names
}

// Reads `'tool-name': factory,` entries of the registry and the `./path` each factory is imported
// from. Entries it cannot follow (a computed key, a spread, an inline factory) fall back to the
// directory.
function parseHandwrittenTools(registrySource) {
    const modules = new Map()
    for (const [, defaultImport, namedImports, path] of registrySource.matchAll(
        /^import (?:(\w+)|\{([^}]*)\}) from '\.\/([^']+)'/gm
    )) {
        for (const name of defaultImport ? [defaultImport] : namedImports.split(',')) {
            modules.set(name.trim(), `${HANDWRITTEN_TOOL_PATH}/${path}`)
        }
    }
    const tools = []
    for (const [, tool, factory] of registrySource.matchAll(/^ {4}'([a-z0-9-]+)': (\w+),$/gm)) {
        if (modules.has(factory)) {
            tools.push([tool, modules.get(factory)])
        }
    }
    return tools
}

function toolDefinitionIndex({
    listFiles = trackedDefinitionFiles,
    readFile = (path) => readFileSync(path, 'utf8'),
} = {}) {
    const index = new Map()
    for (const path of listFiles()) {
        for (const name of parseToolNames(readFile(path))) {
            if (!index.has(name)) {
                index.set(name, path)
            }
        }
    }
    for (const [name, path] of parseHandwrittenTools(readFile(HANDWRITTEN_TOOL_REGISTRY))) {
        if (!index.has(name)) {
            index.set(name, path)
        }
    }
    return index
}

function trackedDefinitionFiles() {
    return execFileSync('git', ['ls-files', ...TOOL_DEFINITION_GLOBS], { encoding: 'utf8' })
        .split('\n')
        .filter(Boolean)
}

function definitionPathFor(tool, index) {
    return index.get(tool) || HANDWRITTEN_TOOL_PATH
}

function formatRate(errors, calls) {
    return `${Math.round((errors * 100) / calls)}%`
}

function tableRows(items, ownerFor) {
    return items.map((item) => [
        cell(item.tool),
        cell(teamLabel(ownerFor(item).owner)),
        cell(String(item.errors)),
        cell(formatRate(item.errors, item.calls)),
        cell(String(item.users)),
        cell(item.topError || 'no message captured'),
    ])
}

function toolTable(rows) {
    return {
        type: 'table',
        column_settings: [
            { align: 'left' },
            { align: 'left' },
            { align: 'right' },
            { align: 'right' },
            { align: 'right' },
            { align: 'left' },
        ],
        rows: [
            [
                cell('tool'),
                cell('owner'),
                cell('failed calls'),
                cell('error rate'),
                cell('users hit'),
                cell('top error'),
            ],
            ...rows,
        ],
    }
}

function reportTitle(now, scope) {
    return `*Weekly MCP tool health - ${now.toISOString().slice(0, 10)}* _(${scope})_`
}

const FLOOR_NOTE = `A tool is listed when it failed at least ${MIN_ERRORS} calls, on at least ${MIN_ERROR_RATE_PCT}% of its calls, for at least ${MIN_USERS} users, in the last ${REPORT_WINDOW_DAYS} days.`

function buildBlocks(now, rows) {
    const blocks = [
        {
            type: 'section',
            text: { type: 'mrkdwn', text: reportTitle(now, `all teams, last ${REPORT_WINDOW_DAYS} days`) },
        },
        toolTable(rows),
        { type: 'context', elements: [{ type: 'mrkdwn', text: FLOOR_NOTE }] },
    ]
    const editBlock = editWorkflowBlock()
    return editBlock ? [...blocks, editBlock] : blocks
}

function buildTeamBlocks(now, { owner, rows }, digestUrl) {
    const footer = [
        ...(digestUrl ? [`<${digestUrl}|Report for all teams>`] : []),
        `${FLOOR_NOTE} Wrong owner or a tool that should be off? Tell ${FEEDBACK_CHANNEL}.`,
    ]
    return [
        { type: 'section', text: { type: 'mrkdwn', text: reportTitle(now, `owned by ${teamLabel(owner)}`) } },
        toolTable(rows),
        { type: 'context', elements: [{ type: 'mrkdwn', text: footer.join(' · ') }] },
    ]
}

// A slice kept in the digest thread. `reason` says why it is not in the team's channel.
function buildThreadSliceBlocks({ owner, channel, rows }, reason) {
    return [
        { type: 'section', text: { type: 'mrkdwn', text: `*${teamLabel(owner)}* _(${reason} ${channel})_` } },
        toolTable(rows),
    ]
}

function teamReport(now) {
    return {
        title: 'Weekly MCP tool health report',
        rowLabel: 'tools',
        teamBlocks: (team, digestUrl) => buildTeamBlocks(now, team, digestUrl),
        threadSliceBlocks: buildThreadSliceBlocks,
    }
}

// Off, each slice goes to the digest thread, labeled with the channel it would reach, so the
// routing can be checked before any team channel receives a post.
function teamPostsWithheld(enabled = TEAM_CHANNEL_POSTS) {
    return enabled ? null : 'shadow: would post to'
}

// A null channel on an owned tool means the team set `mcp_tool_health: false` in owners.yaml, which
// opts it out of this report everywhere, its inbox included.
function ownedTeams(items, ownerFor) {
    const byOwner = new Map()
    for (const item of items) {
        const { owner, slack } = ownerFor(item)
        if (owner === 'unowned' || !slack) {
            continue
        }
        if (!byOwner.has(owner)) {
            byOwner.set(owner, { owner, items: [] })
        }
        byOwner.get(owner).items.push(item)
    }
    return [...byOwner.values()].sort((a, b) => b.items.length - a.items.length)
}

function toolLine(item) {
    return `\`${item.tool}\` failed ${item.errors} of ${item.calls} calls (${formatRate(item.errors, item.calls)}) for ${item.users} users. Top error: ${item.topError || 'no message captured'}`
}

function signalReport(now, { owner, items }, reviewerUuids) {
    // The Monday that starts the run's week, so a re-run later that week replays rather than duplicates.
    const monday = new Date(
        Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate() - ((now.getUTCDay() + 6) % 7))
    )
    const week = monday.toISOString().slice(0, 10)
    const count = items.length === 1 ? '1 MCP tool is' : `${items.length} MCP tools are`
    const reviewers = reviewerUuids.slice(0, MAX_SIGNAL_REVIEWERS).map((uuid) => ({
        user_uuid: uuid,
        reason: `Member of the role for ${owner}, which owns these tools in owners.yaml.`,
    }))
    return {
        title: `fix(mcp): ${count} failing for agents (${teamLabel(owner)})`,
        summary: [
            `${count} failing for AI agents in the PostHog MCP server, and the ${teamLabel(owner)} team owns their definitions.`,
            '',
            ...items.map((item) => `- ${toolLine(item)}`),
            '',
            `${FLOOR_NOTE} Wrong owner or a tool that should be off? Tell ${FEEDBACK_CHANNEL}.`,
        ].join('\n'),
        evidence: items.map((item) => ({
            source_id: item.tool,
            description: `Defined in ${item.selector}: ${toolLine(item)}`,
        })),
        actionability: 'immediately_actionable',
        actionability_explanation: `Each tool failed for at least ${MIN_USERS} users on at least ${MIN_ERROR_RATE_PCT}% of its calls in the last ${REPORT_WINDOW_DAYS} days, and the top error names where to look.`,
        repository: GITHUB_REPOSITORY,
        tags: ['mcp-tool-health', owner],
        idempotency_key: `mcp-tool-health:${week}:${owner}`,
        ...(reviewers.length > 0 ? { suggested_reviewers: reviewers } : {}),
    }
}

const roleKey = (name) =>
    name
        .toLowerCase()
        .replace(/^team\b/, '')
        .replace(/[^a-z0-9]/g, '')

function roleMembers(roles, owner) {
    const key = roleKey(ROLE_FOR_TEAM[owner] ?? owner)
    const role = roles.find((candidate) => roleKey(candidate.name) === key)
    return (role?.members ?? []).map((member) => member.user?.uuid).filter(Boolean)
}

const signalsGet = (path) =>
    requestPosthog(`${HOST}${path}`, { headers: { Authorization: `Bearer ${SIGNALS_API_KEY}` } }, path)

// Roles still list deactivated users, and the report API rejects a whole report that names one, so
// reviewers are limited to the organization's active members.
async function fetchReviewerDirectory(projectId = SIGNALS_PROJECT_ID, get = signalsGet) {
    const project = await get(`/api/projects/${projectId}/`)
    const roles = await get(`/api/organizations/${project.organization}/roles/?limit=500`)
    const active = new Set()
    let page = `/api/organizations/${project.organization}/members/?limit=500`
    while (page) {
        const members = await get(page)
        for (const member of members.results) {
            active.add(member.user.uuid)
        }
        page = members.next ? new URL(members.next).pathname + new URL(members.next).search : null
    }
    return (owner) => roleMembers(roles.results, owner).filter((uuid) => active.has(uuid))
}

function fileInboxReport(body) {
    return requestPosthog(
        `${HOST}/api/projects/${SIGNALS_PROJECT_ID}/signals/reports/`,
        {
            method: 'POST',
            headers: { Authorization: `Bearer ${SIGNALS_API_KEY}`, 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        },
        'signals report'
    )
}

// One team's failure, at either step, must not keep the teams behind it from their reports. A team
// whose members can't be read is left unfiled, since a re-run replays a filed report unchanged and
// could never add its reviewers.
async function fileTeamSignals(
    teams,
    { now, deadline = Date.now() + SIGNALS_BUDGET_MS, membersOf, file = fileInboxReport }
) {
    const filed = []
    for (const team of teams) {
        if (Date.now() > deadline) {
            console.warn(`signals delivery budget spent - ${team.owner} and later teams were not filed`)
            break
        }
        try {
            const uuids = await membersOf(team.owner)
            if (uuids.length === 0) {
                console.warn(`no active role members found for ${team.owner}, filing without reviewers`)
            }
            const result = await file(signalReport(now, team, uuids))
            console.info(
                `${team.owner}: inbox report ${result.report_id} (${result.report_status ?? result.skipped_reason})`
            )
            filed.push({ owner: team.owner, reportId: result.report_id })
        } catch (err) {
            console.warn(`signals report for ${team.owner} failed: ${err.message}`)
        }
    }
    return filed
}

async function main() {
    if (!PROJECT_ID || !API_KEY) {
        console.warn('POSTHOG_PROJECT_ID / POSTHOG_API_KEY not set - skipping report. Wire them to enable.')
        return
    }
    const now = new Date()
    const failing = await fetchFailingTools()
    if (failing.length === 0) {
        console.info('No MCP tool above the failure floor this week - nothing to post.')
        return
    }
    const index = toolDefinitionIndex()
    const items = failing.map((item) => ({ ...item, selector: definitionPathFor(item.tool, index) }))
    const ownerFor = resolveOwners(items, (path) => [path], OWNERS_PRODUCER)
    const rows = tableRows(items, ownerFor)
    const entries = items.map((item, i) => ({ ...ownerFor(item), row: rows[i] }))
    const blocks = buildBlocks(now, rows)
    const teamDigests = buildTeamDigests(entries)
    const signalTeams = ownedTeams(items, ownerFor)
    if (DRY_RUN) {
        // Actions logs on this public repo are readable by anyone, so a dry run prints only the routing.
        // Shadow mode previews the full report, with its counts and errors, in the Slack digest thread.
        for (const item of items) {
            const { owner, slack } = ownerFor(item)
            console.info(`${item.tool} -> ${owner} (${slack ?? 'digest only'})`)
        }
        console.info(`Would file inbox reports for: ${signalTeams.map((t) => t.owner).join(', ') || 'no team'}`)
        return
    }
    if (!SLACK_BOT_TOKEN) {
        throw new Error('SLACK_BOT_TOKEN not set on a non-dry run - refusing to silently skip.')
    }
    const digest = await postToSlack(blocks, 'Weekly MCP tool health report')
    console.info(`Posted weekly MCP tool health report to ${SLACK_CHANNEL}.`)
    const posted = await deliverTeamDigests(teamDigests, {
        digest,
        report: teamReport(now),
        withheld: teamPostsWithheld(),
    })
    console.info(`Posted ${posted.length}/${teamDigests.length} team slice(s) to team channels.`)
    if (!SIGNALS_PROJECT_ID || !SIGNALS_API_KEY) {
        console.warn('SIGNALS_PROJECT_ID / SIGNALS_API_KEY not set - skipping team signals reports.')
        return
    }
    let directory
    const filed = await fileTeamSignals(signalTeams, {
        now,
        membersOf: async (owner) => (await (directory ??= fetchReviewerDirectory()))(owner),
    })
    console.info(`Filed ${filed.length}/${signalTeams.length} team signals report(s).`)
    // Every team is still attempted, but any team left without a report fails the run. A re-run that
    // week replays the reports already filed and files the rest.
    if (filed.length < signalTeams.length) {
        process.exitCode = 1
    }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
    main().catch((err) => {
        console.error(err)
        process.exit(1)
    })
}

export {
    definitionPathFor,
    fetchFailingTools,
    fetchReviewerDirectory,
    fileTeamSignals,
    HANDWRITTEN_TOOL_PATH,
    MAX_SIGNAL_REVIEWERS,
    ownedTeams,
    roleMembers,
    signalReport,
    teamPostsWithheld,
    teamReport,
    toolDefinitionIndex,
}
