import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import {
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
} from './weekly-mcp-tool-health-report.mjs'
import { deliverTeamDigests, resolveOwners } from './weekly-report-common.mjs'

const DEFINITION = `category: Surveys
ui_apps:
    survey-list:
        type: list
tools:
    survey-create:
        operation: surveys_create
        param_overrides:
            name:
                aliases:
    survey-get:
        operation: surveys_retrieve
    survey-delete:
        operation: surveys_destroy
        confirmed_action:
            action_label: Delete survey
wrappers:
    query-survey:
        schema_ref: SurveyQuery
`

const REGISTRY = `import getLLMCosts from './aiObservability/getLLMCosts'
import {
    executeSql,
    readDataSchema,
} from './posthogAiTools'

export const TOOL_MAP = {
    'get-llm-total-costs-for-project': getLLMCosts,
    'read-data-schema': readDataSchema,
    [EXECUTE_SQL_TOOL_NAME]: executeSql,
    'posthog-connection-call': () => createConnectionCallTool(resolveToolBase),
}
`

const TEAM = { owner: 'team-surveys', channel: '#team-surveys', rows: [['row']] }

// A slice's heading, a team post's digest link, or the index's header row.
function lastNote(blocks) {
    const notes = blocks
        .filter((block) => block.type !== 'table')
        .map((block) => (block.text ?? block.elements[0]).text)
    return notes.length > 0 ? notes.at(-1).split(' · ')[0] : blocks[0].rows[0].map((c) => c.text).join(' | ')
}

function recordingSlack() {
    const posts = []
    return {
        posts,
        slack: {
            post: async (blocks, text, options) => {
                posts.push({ ...options, note: lastNote(blocks) })
                return { ts: '2.0', channel: options.channel || 'C_DIGEST' }
            },
            permalink: async ({ channel, ts }) => `https://slack.test/${channel}/${ts}`,
            pause: async () => {},
        },
    }
}

describe('weekly MCP tool health report', () => {
    it('maps tools, wrappers and handwritten tools to their source file and nothing else', () => {
        const index = toolDefinitionIndex({
            listFiles: () => ['products/surveys/mcp/tools.yaml'],
            readFile: (path) => (path.endsWith('index.ts') ? REGISTRY : DEFINITION),
        })
        assert.deepEqual(
            [...index.entries()],
            [
                ['survey-create', 'products/surveys/mcp/tools.yaml'],
                ['survey-get', 'products/surveys/mcp/tools.yaml'],
                ['survey-delete-prepare', 'products/surveys/mcp/tools.yaml'],
                ['survey-delete-execute', 'products/surveys/mcp/tools.yaml'],
                ['query-survey', 'products/surveys/mcp/tools.yaml'],
                ['get-llm-total-costs-for-project', 'services/mcp/src/tools/aiObservability/getLLMCosts'],
                ['read-data-schema', 'services/mcp/src/tools/posthogAiTools'],
            ]
        )
        assert.equal(definitionPathFor('execute-sql', index), HANDWRITTEN_TOOL_PATH)
    })

    it('resolves owners for the report producer through owners.yaml', () => {
        const items = [{ selector: 'products/cdp/mcp/cdp_functions.yaml' }, { selector: HANDWRITTEN_TOOL_PATH }]
        const ownerFor = resolveOwners(items, (path) => [path], 'mcp_tool_health')
        for (const item of items) {
            assert.notEqual(ownerFor(item).owner, 'unowned')
        }
    })

    it('reads query rows into tool records', async () => {
        const tools = await fetchFailingTools(async () => ({
            results: [['survey-get', '120', '30', '7', null]],
        }))
        assert.deepEqual(tools, [{ tool: 'survey-get', calls: 120, errors: 30, users: 7, topError: '' }])
    })

    for (const { label, enabled, digestChannel = '#team-context-and-mcp', expected } of [
        {
            label: 'keeps every slice in the thread while team posts are off',
            enabled: false,
            expected: [{ threadTs: '1.0', note: '*surveys* _(shadow: would post to #team-surveys)_' }],
        },
        {
            label: 'posts a slice to its team channel and indexes it when team posts are on',
            enabled: true,
            expected: [
                { channel: '#team-surveys', note: '<https://slack.test/C_DIGEST/1.0|Report for all teams>' },
                { threadTs: '1.0', note: 'team | tools | post' },
            ],
        },
        {
            label: 'keeps the slice of the digest channel team in the thread',
            enabled: true,
            digestChannel: '#team-surveys',
            expected: [{ threadTs: '1.0', note: '*surveys* _(report already in #team-surveys)_' }],
        },
    ]) {
        it(label, async () => {
            const { posts, slack } = recordingSlack()
            await deliverTeamDigests([TEAM], {
                digest: { ts: '1.0', channel: 'C_DIGEST' },
                report: teamReport(new Date('2026-10-26T00:00:00Z')),
                withheld: teamPostsWithheld(enabled),
                digestChannel,
                slack,
            })
            assert.deepEqual(posts, expected)
        })
    }

    describe('signals to owning teams', () => {
        const NOW = new Date('2026-10-26T13:50:00Z')
        const TOOL = { tool: 'survey-get', calls: 120, errors: 30, users: 7, topError: 'GET /api/#/ -> 500' }
        const SURVEYS = { owner: 'team-surveys', items: [TOOL] }

        it('groups failing tools by owning team and leaves unowned tools out', () => {
            const items = [
                { tool: 'survey-get', owner: 'team-surveys' },
                { tool: 'execute-sql', owner: 'unowned' },
                { tool: 'survey-create', owner: 'team-surveys' },
            ]
            const teams = ownedTeams(items, (item) => ({ owner: item.owner, slack: `#${item.owner}` }))
            assert.deepEqual(
                teams.map((team) => [team.owner, team.items.map((item) => item.tool)]),
                [['team-surveys', ['survey-get', 'survey-create']]]
            )
        })

        it('files nothing for a team that silenced this report in owners.yaml', () => {
            const items = [{ tool: 'survey-get', owner: 'team-surveys', slack: null }]
            assert.deepEqual(
                ownedTeams(items, (item) => item),
                []
            )
        })

        it('keys the report on the week and team so a later re-run returns the first report', () => {
            const thursday = new Date('2026-10-29T09:00:00Z')
            assert.equal(signalReport(thursday, SURVEYS, []).idempotency_key, 'mcp-tool-health:2026-10-26:team-surveys')
        })

        it('backs the report with one piece of evidence per failing tool', () => {
            assert.deepEqual(
                signalReport(NOW, SURVEYS, []).evidence.map((entry) => entry.source_id),
                ['survey-get']
            )
        })

        it('routes the report to the owning team members, capped at the reviewer limit', () => {
            const uuids = Array.from({ length: MAX_SIGNAL_REVIEWERS + 2 }, (_, i) => `uuid-${i}`)
            assert.equal(signalReport(NOW, SURVEYS, uuids).suggested_reviewers.length, MAX_SIGNAL_REVIEWERS)
        })

        it('names each reviewer by PostHog user so members without a linked GitHub account are reached', () => {
            assert.equal(signalReport(NOW, SURVEYS, ['uuid-1']).suggested_reviewers[0].user_uuid, 'uuid-1')
        })

        const role = (name, ...uuids) => ({ name, members: uuids.map((uuid) => ({ user: { uuid } })) })
        const ROLES = [
            role('Team Feature Flags', 'flags-1'),
            role('Team Conversations', 'conv-1'),
            role('Team Developer Experience', 'devex-1'),
        ]
        for (const [owner, expected] of [
            ['team-feature-flags', ['flags-1']],
            ['conversations', ['conv-1']],
            ['team-devex', ['devex-1']],
            ['team-agent-infrastructure', []],
        ]) {
            it(`finds the role members for the ${owner} GitHub team`, () => {
                assert.deepEqual(roleMembers(ROLES, owner), expected)
            })
        }

        it('tags the report with the owning team', () => {
            assert.deepEqual(signalReport(NOW, SURVEYS, []).tags, ['mcp-tool-health', 'team-surveys'])
        })

        it('files nothing for a team whose members cannot be read, so a re-run can still route it', async () => {
            const reports = await fileTeamSignals([SURVEYS], {
                now: NOW,
                membersOf: async () => {
                    throw new Error('403')
                },
                file: async () => ({ report_id: 'r1' }),
            })
            assert.deepEqual(reports, [])
        })

        it('leaves deactivated role members out of the reviewers', async () => {
            const pages = {
                '/api/projects/2/': { organization: 'org' },
                '/api/organizations/org/roles/?limit=500': { results: [role('Team Surveys', 'active', 'gone')] },
                '/api/organizations/org/members/?limit=500': { results: [{ user: { uuid: 'active' } }], next: null },
            }
            const membersOf = await fetchReviewerDirectory('2', async (url) => pages[url])
            assert.deepEqual(membersOf('team-surveys'), ['active'])
        })

        it('starts no team once the delivery deadline has passed', async () => {
            const reports = await fileTeamSignals([SURVEYS], {
                now: NOW,
                deadline: Date.now() - 1,
                membersOf: async () => [],
                file: async () => ({ report_id: 'r3' }),
            })
            assert.deepEqual(reports, [])
        })

        it('files nothing when the reviewer lookup runs past the delivery deadline', async () => {
            const reports = await fileTeamSignals([SURVEYS], {
                now: NOW,
                deadline: Date.now() + 20,
                membersOf: () => new Promise((resolve) => setTimeout(() => resolve([]), 40)),
                file: async () => ({ report_id: 'r4' }),
            })
            assert.deepEqual(reports, [])
        })

        it('keeps the organization id out of reviewer lookup errors, since Actions logs are public', async () => {
            const labels = []
            const pages = {
                '/api/projects/2/': { organization: 'org-uuid' },
                '/api/organizations/org-uuid/roles/?limit=500': { results: [] },
                '/api/organizations/org-uuid/members/?limit=500': { results: [], next: null },
            }
            await fetchReviewerDirectory('2', async (path, label) => {
                labels.push(label)
                return pages[path]
            })
            assert.ok(labels.every((label) => !label.includes('org-uuid')))
        })

        it('keeps filing the next team after one team fails', async () => {
            const reports = await fileTeamSignals([SURVEYS, { owner: 'team-cdp', items: [TOOL] }], {
                now: NOW,
                membersOf: async () => [],
                file: async (body) => {
                    if (body.tags.includes('team-surveys')) {
                        throw new Error('500')
                    }
                    return { report_id: 'r2' }
                },
            })
            assert.deepEqual(reports, [{ owner: 'team-cdp', reportId: 'r2' }])
        })
    })
})
