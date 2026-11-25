// Weekly MCP tool health report, posted to the MCP team's channel on Monday.
//
// Sibling of weekly-flaky-report.mjs: one HogQL read of the `$mcp_tool_call` events the MCP
// server already captures, ranked by failed calls, with owner attribution through
// packages/owners-yaml. Each tool maps to the YAML file that defines it, so the team that owns
// the definition sees its own failing tools without the MCP team relaying them: each owning team
// also gets Signals inbox reports, suggested to the members of the PostHog role named after
// its GitHub team. Unowned tools stay in the Slack digest only.
//
//   GHA cron ──> HogQL over $mcp_tool_call ──> owners.yaml ──> Slack digest
//                                                         └──> Signals inbox report per team

import { execFileSync } from 'node:child_process'
import { createHash } from 'node:crypto'
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
    linkedCell,
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
const MAX_SIGNAL_EVIDENCE = 50
const MAX_SIGNAL_SUMMARY_LENGTH = 20000
const MAX_NEW_SIGNAL_REPORTS = 20
// Each request can spend about 8.5 minutes on retries, so no team starts or files past this budget,
// and the job's timeout-minutes leaves room for the query and one last slow reviewer lookup.
const SIGNALS_BUDGET_MS = 10 * 60_000

const REPORT_WINDOW_DAYS = 7
const TOP_N = 25
const MIN_ERRORS = 50
const MIN_ERROR_RATE_PCT = 10
const MIN_USERS = 5
const MIN_BACKEND_ERRORS = 5
const MIN_BACKEND_USERS = 3
const MIN_RATE_INCREASE = 5
const SLACK_TOOL_ROWS = 99
const SLACK_TABLE_CHARACTERS = 10000

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
    SELECT tool, is_current, calls, errors, users, command_errors, validation_errors, backend_errors, backend_users, top_error
    FROM (
        SELECT
            tool,
            if(timestamp >= toDateTime({period_end}, 'UTC') - INTERVAL ${REPORT_WINDOW_DAYS} DAY, 1, 0) AS is_current,
            count() AS calls,
            countIf(is_error) AS errors,
            uniqIf(person_id, is_error) AS users,
            countIf(is_error AND is_command_error) AS command_errors,
            countIf(is_error AND error_type = 'validation' AND NOT is_command_error) AS validation_errors,
            countIf(is_error AND is_backend_error) AS backend_errors,
            uniqIf(person_id, is_error AND is_backend_error) AS backend_users,
            arrayElement(topK(1)(if(is_current = 1 AND is_error, replaceRegexpAll(substring(error_message, 1, 160), '/[0-9a-f]{8}-[0-9a-f-]+|/[0-9]+', '/#'), NULL)), 1) AS top_error
        FROM (
            SELECT
                timestamp,
                person_id,
                coalesce(nullIf(toString(properties.$mcp_exec_tool_call_name), ''), toString(properties.$mcp_tool_name)) AS tool,
                toBool(properties.$mcp_is_error) AS is_error,
                toString(properties.$mcp_error_type) AS error_type,
                toString(properties.$mcp_error_message) AS error_message,
                startsWith(coalesce(error_message, ''), 'Exec command rejected:') AS is_command_error,
                error_type IN ('api_5xx', 'timeout', 'memory_limit') AND NOT is_command_error AS is_backend_error
            FROM events
            WHERE event = '$mcp_tool_call'
                AND timestamp >= toDateTime({period_end}, 'UTC') - INTERVAL ${2 * REPORT_WINDOW_DAYS} DAY
                AND timestamp < toDateTime({period_end}, 'UTC')
        )
        WHERE tool IN {known_tools}
        GROUP BY tool, is_current
    )
    WHERE tool NOT IN ('exec', '.', '..')
        AND match(tool, '^[A-Za-z0-9_.-]{1,128}$')
        AND (
            (errors >= {min_errors} AND errors * 100 >= calls * {min_error_rate_pct} AND users >= {min_users})
            OR (backend_errors >= {min_backend_errors} AND backend_users >= {min_backend_users})
        )
    LIMIT {row_limit}`

const TOOL_HEALTH_VALUES = {
    min_errors: MIN_ERRORS,
    min_error_rate_pct: MIN_ERROR_RATE_PCT,
    min_users: MIN_USERS,
    min_backend_errors: MIN_BACKEND_ERRORS,
    min_backend_users: MIN_BACKEND_USERS,
}

function weekStart(date) {
    return new Date(
        Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate() - ((date.getUTCDay() + 6) % 7))
    )
}

function knownToolNames() {
    const schemas = ['tool-definitions.json', 'generated-tool-definitions.json']
    return [
        ...new Set(
            schemas.flatMap((schema) => Object.keys(JSON.parse(readFileSync(`services/mcp/schema/${schema}`, 'utf8'))))
        ),
    ]
}

async function fetchFailingTools(runHogql = hogql, now = new Date(), knownTools = knownToolNames()) {
    const result = await runHogql(TOOL_HEALTH_QUERY, {
        ...TOOL_HEALTH_VALUES,
        period_end: weekStart(now).getTime() / 1000,
        known_tools: knownTools,
        row_limit: 2 * knownTools.length,
    })
    return result.results.map(
        ([
            tool,
            current,
            calls,
            errors,
            users,
            commandErrors,
            validationErrors,
            backendErrors,
            backendUsers,
            topError,
        ]) => ({
            tool,
            current: Number(current) === 1,
            calls: Number(calls),
            errors: Number(errors),
            users: Number(users),
            commandErrors: Number(commandErrors),
            validationErrors: Number(validationErrors),
            backendErrors: Number(backendErrors),
            backendUsers: Number(backendUsers),
            topError: topError || '',
        })
    )
}

function backendQualifies({ backendErrors, backendUsers }) {
    return backendErrors >= MIN_BACKEND_ERRORS && backendUsers >= MIN_BACKEND_USERS
}

function reportItems(results) {
    const previous = new Map(results.filter((item) => !item.current).map((item) => [item.tool, item]))
    const items = results
        .filter((item) => item.current)
        .map((item) => {
            const prior = previous.get(item.tool)
            previous.delete(item.tool)
            if (!prior) {
                return { ...item, change: 'New' }
            }
            const rateWorsened =
                (item.errors * prior.calls - prior.errors * item.calls) * 100 >=
                MIN_RATE_INCREASE * item.calls * prior.calls
            let changeDetail
            if (backendQualifies(item) && !backendQualifies(prior)) {
                changeDetail = 'Backend failures now qualify'
            } else if (backendQualifies(item) && item.backendErrors - prior.backendErrors >= MIN_BACKEND_ERRORS) {
                changeDetail = `Backend failures ${prior.backendErrors} → ${item.backendErrors}`
            } else if (rateWorsened) {
                changeDetail = `Error rate ${formatRate(prior.errors, prior.calls)} → ${formatRate(item.errors, item.calls)}`
            }
            return { ...item, change: changeDetail ? 'Worsening' : 'Recurring', changeDetail }
        })
    items.sort(
        (a, b) =>
            Number(backendQualifies(b)) - Number(backendQualifies(a)) ||
            b.errors - a.errors ||
            a.tool.localeCompare(b.tool)
    )
    return [...items, ...Array.from(previous.values(), (item) => ({ ...item, change: 'Below threshold' }))]
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

function toolQualityUrl(now, tool) {
    const start = new Date(now.getTime() - REPORT_WINDOW_DAYS * 24 * 60 * 60 * 1000)
    const url = new URL(`/project/${PROJECT_ID}/mcp-analytics/tool-quality/${encodeURIComponent(tool)}`, HOST)
    url.searchParams.set('date_from', start.toISOString())
    url.searchParams.set('date_to', now.toISOString())
    return url.toString()
}

function errorBreakdown(item) {
    const { errors, commandErrors, validationErrors, backendErrors } = item
    return [
        ['Backend', backendErrors],
        ['Command', commandErrors],
        ['Validation', validationErrors],
        ['Other', errors - backendErrors - commandErrors - validationErrors],
    ]
        .filter(([, count]) => count > 0)
        .map(([label, count]) => `${label} ${count}`)
        .join(' · ')
}

function tableRows(now, items, ownerFor) {
    return items.map((item) => [
        linkedCell([{ text: item.tool, url: toolQualityUrl(now, item.tool) }]),
        cell(teamLabel(ownerFor(item).owner)),
        cell(item.changeDetail ? `${item.change} · ${item.changeDetail}` : item.change),
        cell(`${item.errors}/${item.calls} (${formatRate(item.errors, item.calls)})`),
        cell(String(item.users)),
        cell(errorBreakdown(item)),
        cell(item.topError || 'no message captured'),
    ])
}

function reportTableBlocks(rows, limit) {
    const headers = [
        cell('Tool'),
        cell('Owner'),
        cell('Since last week'),
        cell('Failed calls'),
        cell('Users hit'),
        cell('Failure counts'),
        cell('Top error'),
    ]
    const table = {
        type: 'table',
        column_settings: [
            { align: 'left', is_wrapped: true },
            { align: 'left' },
            { align: 'left', is_wrapped: true },
            { align: 'right' },
            { align: 'right' },
            { align: 'left', is_wrapped: true },
            { align: 'left', is_wrapped: true },
        ],
        rows: [headers],
    }
    let remaining = SLACK_TABLE_CHARACTERS - headers.reduce((length, header) => length + header.text.length, 0)
    for (const row of rows.slice(0, limit)) {
        const size = row.reduce((length, entry) => {
            const link = entry.elements?.[0].elements[0]
            return length + (link ? link.text.length + link.url.length : entry.text.length)
        }, 0)
        if (size > remaining) {
            break
        }
        table.rows.push(row)
        remaining -= size
    }
    const shown = table.rows.length - 1
    const blocks = shown ? [table] : []
    if (shown < rows.length) {
        blocks.push({
            type: 'context',
            elements: [
                {
                    type: 'mrkdwn',
                    text: `Showing ${shown} of ${rows.length} qualifying tools.`,
                },
            ],
        })
    }
    return blocks
}

function reportTitle(now, scope) {
    return `*Weekly MCP tool health - ${now.toISOString().slice(0, 10)}* _(${scope})_`
}

const FLOOR_NOTE = `A tool qualifies with ${MIN_ERRORS}+ failed calls, a ${MIN_ERROR_RATE_PCT}%+ error rate, and ${MIN_USERS}+ users affected. Backend errors (5xx, timeouts, or memory limits) qualify at ${MIN_BACKEND_ERRORS}+ failures affecting ${MIN_BACKEND_USERS}+ users.`
const DRILLDOWN_NOTE = 'Tool links use the hosted MCP analytics filters. Report totals also include CLI activity.'

function buildBlocks(now, rows, belowThreshold) {
    const blocks = [
        {
            type: 'section',
            text: { type: 'mrkdwn', text: reportTitle(now, `all teams, last ${REPORT_WINDOW_DAYS} days`) },
        },
        ...reportTableBlocks(rows, TOP_N),
    ]
    if (belowThreshold.length) {
        const examples = belowThreshold
            .slice(0, TOP_N)
            .map(({ tool }) => tool)
            .join(', ')
        const shortened = examples.length > 2700 || belowThreshold.length > TOP_N
        blocks.push({
            type: 'section',
            text: {
                type: 'plain_text',
                text: `Below the reporting threshold this week (${belowThreshold.length})\n${shortened ? `${examples.slice(0, 2699)}…` : examples}`,
            },
        })
    }
    blocks.push({ type: 'context', elements: [{ type: 'mrkdwn', text: `${FLOOR_NOTE} ${DRILLDOWN_NOTE}` }] })
    const editBlock = editWorkflowBlock()
    return editBlock ? [...blocks, editBlock] : blocks
}

function buildTeamBlocks(now, { owner, rows }, digestUrl) {
    const footer = [
        ...(digestUrl ? [`<${digestUrl}|Report for all teams>`] : []),
        `${FLOOR_NOTE} ${DRILLDOWN_NOTE} Wrong owner or a tool that should be off? Tell ${FEEDBACK_CHANNEL}.`,
    ]
    return [
        {
            type: 'section',
            text: { type: 'mrkdwn', text: reportTitle(now, `new or worsening for ${teamLabel(owner)}`) },
        },
        ...reportTableBlocks(rows, SLACK_TOOL_ROWS),
        { type: 'context', elements: [{ type: 'mrkdwn', text: footer.join(' · ') }] },
    ]
}

// A slice kept in the digest thread. `reason` says why it is not in the team's channel.
function buildThreadSliceBlocks({ owner, channel, rows }, reason) {
    return [
        { type: 'section', text: { type: 'mrkdwn', text: `*${teamLabel(owner)}* _(${reason} ${channel})_` } },
        ...reportTableBlocks(rows, SLACK_TOOL_ROWS),
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

function toolLine(now, item) {
    const change = item.changeDetail ? `${item.change} (${item.changeDetail})` : item.change
    const message = item.topError?.replace(/\s+/g, ' ').trim() || 'no message captured'
    const longestRun = Math.max(0, ...(message.match(/`+/g) ?? []).map((run) => run.length))
    const fence = '`'.repeat(longestRun + 1)
    return `${change}: [\`${item.tool}\`](${toolQualityUrl(now, item.tool)}) failed ${item.errors} of ${item.calls} calls (${formatRate(item.errors, item.calls)}) for ${item.users} users. ${errorBreakdown(item)}. Top error: ${fence} ${message} ${fence}`
}

function signalReport(now, { owner, items, part = 1, parts = 1 }, reviewerUuids) {
    const week = weekStart(now).toISOString().slice(0, 10)
    const membership = createHash('sha256')
        .update(JSON.stringify(items.map(({ tool }) => tool).sort()))
        .digest('hex')
    const count = items.length === 1 ? '1 MCP tool is' : `${items.length} MCP tools are`
    const partLabel = parts > 1 ? ` (part ${part} of ${parts})` : ''
    const headline = `${count} failing for AI agents, and the ${teamLabel(owner)} team owns their definitions.`
    const footer = `${FLOOR_NOTE} ${DRILLDOWN_NOTE} Wrong owner or a tool that should be off? Tell ${FEEDBACK_CHANNEL}.`
    const lines = items.map((item) => toolLine(now, item))
    let summary = [headline, '', ...lines.map((line) => `- ${line}`), '', footer].join('\n')
    if (summary.length > MAX_SIGNAL_SUMMARY_LENGTH) {
        summary = [headline, '', 'See the evidence for the failure breakdown and tool links.', '', footer].join('\n')
    }
    const reviewers = reviewerUuids.slice(0, MAX_SIGNAL_REVIEWERS).map((uuid) => ({
        user_uuid: uuid,
        reason: `Member of the role for ${owner}, which owns these tools in owners.yaml.`,
    }))
    return {
        title: `fix(mcp): ${count} failing for agents (${teamLabel(owner)})${partLabel}`,
        summary,
        evidence: items.map((item, index) => ({
            source_id: item.tool,
            description: `Defined in ${item.selector}: ${lines[index]}`,
        })),
        actionability: 'immediately_actionable',
        actionability_explanation:
            'Each tool crossed a weekly reporting threshold. The error breakdown and tool quality link give the owning team somewhere to start investigating.',
        repository: GITHUB_REPOSITORY,
        tags: ['mcp-tool-health', owner],
        idempotency_key: `mcp-tool-health:${week}:${owner}:${membership}`,
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

// Errors carry the label, not the path, so the organization id stays out of the public Actions logs.
const signalsGet = (path, label) =>
    requestPosthog(`${HOST}${path}`, { headers: { Authorization: `Bearer ${SIGNALS_API_KEY}` } }, label)

// Roles still list deactivated users, and the report API rejects a whole report that names one, so
// reviewers are limited to the organization's active members.
async function fetchReviewerDirectory(projectId = SIGNALS_PROJECT_ID, get = signalsGet) {
    const project = await get(`/api/projects/${projectId}/`, 'signals project')
    const roles = await get(`/api/organizations/${project.organization}/roles/?limit=500`, 'organization roles')
    const active = new Set()
    let page = `/api/organizations/${project.organization}/members/?limit=500`
    while (page) {
        const members = await get(page, 'organization members')
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
    const reviewers = new Map()
    let newReports = 0
    const batches = teams.flatMap(({ owner, items }) => {
        // Stable tool order keeps changes in error rankings from moving evidence between reports.
        const sorted = items.toSorted((a, b) => a.tool.localeCompare(b.tool))
        const parts = Math.ceil(sorted.length / MAX_SIGNAL_EVIDENCE)
        return Array.from({ length: parts }, (_, index) => ({
            owner,
            items: sorted.slice(index * MAX_SIGNAL_EVIDENCE, (index + 1) * MAX_SIGNAL_EVIDENCE),
            part: index + 1,
            parts,
        }))
    })
    // Give each team a report before spending quota on additional parts.
    batches.sort((a, b) => a.part - b.part)
    for (const batch of batches) {
        const { owner, part } = batch
        if (newReports >= MAX_NEW_SIGNAL_REPORTS) {
            console.warn(
                `Signals filing limit reached before ${owner} part ${part}. Retry after the daily quota resets.`
            )
            break
        }
        if (Date.now() > deadline) {
            console.warn(`signals delivery budget spent before filing ${owner} part ${part}`)
            break
        }
        if (!reviewers.has(owner)) {
            try {
                const uuids = await membersOf(owner)
                reviewers.set(owner, uuids)
                if (uuids.length === 0) {
                    console.warn(`no active role members found for ${owner}, filing without reviewers`)
                }
            } catch (err) {
                console.warn(`signals reviewer lookup for ${owner} failed: ${err.message}`)
                reviewers.set(owner, null)
            }
        }
        const uuids = reviewers.get(owner)
        if (!uuids) {
            continue
        }
        if (Date.now() > deadline) {
            console.warn(`signals delivery budget spent before filing ${owner} part ${part}`)
            break
        }
        try {
            const result = await file(signalReport(now, batch, uuids))
            if (!result.report_id) {
                console.warn(`Signals did not file ${owner} part ${part} (${result.skipped_reason ?? 'no report ID'})`)
                continue
            }
            if (!result.idempotent_replay) {
                newReports++
            }
            console.info(
                `${owner}: inbox report ${result.report_id} (${result.report_status ?? result.skipped_reason})`
            )
            filed.push({ owner, reportId: result.report_id })
        } catch (err) {
            console.warn(`signals report for ${owner} part ${part} failed: ${err.message}`)
        }
    }
    return filed
}

async function main() {
    if (!PROJECT_ID || !API_KEY) {
        console.warn('POSTHOG_PROJECT_ID / POSTHOG_API_KEY not set - skipping report. Wire them to enable.')
        return
    }
    const now = weekStart(new Date())
    const findings = reportItems(await fetchFailingTools(hogql, now))
    if (findings.length === 0) {
        console.info('No MCP tools crossed a reporting threshold in either week.')
        return
    }
    const index = toolDefinitionIndex()
    const belowThreshold = findings.filter((item) => !item.current)
    const items = findings
        .filter((item) => item.current)
        .map((item) => ({ ...item, selector: definitionPathFor(item.tool, index) }))
    const ownerFor = resolveOwners(items, (path) => [path], OWNERS_PRODUCER)
    const { blocks, teamDigests } = slackReport(now, items, belowThreshold, ownerFor)
    const signalTeams = ownedTeams(items, ownerFor)
    if (DRY_RUN) {
        // Actions logs on this public repo are readable by anyone, so a dry run prints only the routing.
        // Shadow mode previews team posts in the Slack digest thread.
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
    const expectedReports = signalTeams.reduce(
        (total, team) => total + Math.ceil(team.items.length / MAX_SIGNAL_EVIDENCE),
        0
    )
    console.info(`Filed ${filed.length}/${expectedReports} team signals report(s).`)
    if (filed.length < expectedReports) {
        process.exitCode = 1
    }
}

function slackReport(now, items, belowThreshold, ownerFor) {
    const rows = tableRows(now, items, ownerFor)
    const entries = items.flatMap((item, i) =>
        item.change === 'Recurring' ? [] : [{ ...ownerFor(item), row: rows[i] }]
    )
    return { blocks: buildBlocks(now, rows, belowThreshold), teamDigests: buildTeamDigests(entries) }
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
    reportItems,
    roleMembers,
    signalReport,
    slackReport,
    teamPostsWithheld,
    teamReport,
    toolDefinitionIndex,
}
