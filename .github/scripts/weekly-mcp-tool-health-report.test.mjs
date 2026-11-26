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
    reportItems,
    roleMembers,
    signalReport,
    slackReport,
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

const TEAM = { owner: 'team-surveys', channel: '#team-surveys', rows: [[{ type: 'raw_text', text: 'row' }]] }

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

    it('reads current and previous query rows into tool records', async () => {
        const tools = await fetchFailingTools(
            async () => ({ results: [['survey-get', '1', '120', '30', '7', '12', '8', '5', '3', null]] }),
            new Date('2026-10-26T13:50:00Z'),
            ['survey-get']
        )
        assert.deepEqual(tools, [
            {
                tool: 'survey-get',
                current: true,
                calls: 120,
                errors: 30,
                users: 7,
                commandErrors: 12,
                validationErrors: 8,
                backendErrors: 5,
                backendUsers: 3,
                topError: '',
            },
        ])
    })

    it('queries the same completed UTC week when rerun later in the week', async () => {
        const periodEnds = []
        const query = async (_, { period_end }) => {
            periodEnds.push(period_end)
            return { results: [] }
        }
        await fetchFailingTools(query, new Date('2026-10-26T13:50:00Z'), ['survey-get'])
        await fetchFailingTools(query, new Date('2026-10-29T09:00:00Z'), ['survey-get'])
        const monday = Date.parse('2026-10-26T00:00:00Z') / 1000
        assert.deepEqual(periodEnds, [monday, monday])
    })

    it('binds the registered tool names and budgets one query row per tool per week', async () => {
        await fetchFailingTools(
            async (_, { known_tools, row_limit }) => {
                assert.deepEqual([known_tools, row_limit], [['survey-get', 'execute-sql'], 4])
                return { results: [] }
            },
            new Date('2026-10-26T13:50:00Z'),
            ['survey-get', 'execute-sql']
        )
    })

    it('marks a qualifying tool new when it was below threshold last week', () => {
        assert.equal(reportItems([{ tool: 'survey-get', current: true }])[0].change, 'New')
    })

    it('marks a tool with backend failures newly above threshold as worsening', () => {
        const previous = {
            tool: 'survey-get',
            current: false,
            calls: 600,
            errors: 60,
            backendErrors: 4,
            backendUsers: 3,
        }
        assert.equal(reportItems([previous, { ...previous, current: true, backendErrors: 5 }])[0].change, 'Worsening')
    })

    it('marks an increase of five backend failures as worsening when the overall rate is unchanged', () => {
        const previous = {
            tool: 'survey-get',
            current: false,
            calls: 600,
            errors: 60,
            backendErrors: 5,
            backendUsers: 3,
        }
        assert.equal(reportItems([previous, { ...previous, current: true, backendErrors: 10 }])[0].change, 'Worsening')
    })

    it('marks an unchanged issue recurring', () => {
        const previous = {
            tool: 'survey-get',
            current: false,
            calls: 600,
            errors: 60,
            backendErrors: 0,
            backendUsers: 0,
        }
        assert.equal(reportItems([previous, { ...previous, current: true }])[0].change, 'Recurring')
    })

    it('marks a tool that only qualified last week as below threshold', () => {
        assert.equal(reportItems([{ tool: 'survey-get', current: false }])[0].change, 'Below threshold')
    })

    it('marks an increase of exactly five percentage points as worsening', () => {
        const previous = { tool: 'survey-get', current: false, calls: 600, errors: 90 }
        assert.equal(
            reportItems([previous, { ...previous, current: true, errors: 120 }])[0].changeDetail,
            'Error rate 15% → 20%'
        )
    })

    it('keeps the digest row limit out of team delivery', () => {
        const items = Array.from({ length: 26 }, (_, i) => ({
            tool: `tool-${i}`,
            owner: i === 25 ? 'team-last' : 'team-first',
            change: 'New',
            calls: 600,
            errors: 100,
            users: 30,
            commandErrors: 0,
            validationErrors: 0,
            backendErrors: 0,
        }))
        const ownerFor = ({ owner }) => ({ owner, slack: `#${owner}` })
        const { blocks, teamDigests } = slackReport(new Date('2026-10-26T00:00:00Z'), items, [], ownerFor)
        assert.deepEqual(
            [blocks.find(({ type }) => type === 'table').rows.length, teamDigests.map(({ owner }) => owner)],
            [26, ['team-first', 'team-last']]
        )
    })

    it('keeps recurring findings out of team Slack posts', () => {
        const items = [{ tool: 'survey-get', change: 'Recurring' }]
        const ownerFor = () => ({ owner: 'team-surveys', slack: '#team-surveys' })
        assert.deepEqual(slackReport(new Date('2026-10-26T00:00:00Z'), items, [], ownerFor).teamDigests, [])
    })

    it('keeps oversized team Slack tables under the character limit', () => {
        const rows = Array.from({ length: 80 }, () => [{ type: 'raw_text', text: 'x'.repeat(160) }])
        const blocks = teamReport(new Date('2026-10-26T00:00:00Z')).teamBlocks({ ...TEAM, rows })
        const characters = blocks
            .find(({ type }) => type === 'table')
            .rows.flat()
            .reduce((sum, entry) => sum + entry.text.length, 0)
        assert.ok(characters <= 10000, `Slack table has ${characters} characters`)
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
        const TOOL = {
            tool: 'survey-get',
            calls: 120,
            errors: 30,
            users: 7,
            commandErrors: 2,
            validationErrors: 6,
            backendErrors: 12,
            change: 'Recurring',
            topError: 'GET /api/#/ -> 500',
        }
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
            assert.equal(
                signalReport(thursday, SURVEYS, []).idempotency_key,
                signalReport(NOW, SURVEYS, []).idempotency_key
            )
        })

        it('changes a weekly report key when a batch contains different tools', () => {
            const different = { ...SURVEYS, items: [{ ...TOOL, tool: 'survey-list' }] }
            assert.notEqual(
                signalReport(NOW, different, []).idempotency_key,
                signalReport(NOW, SURVEYS, []).idempotency_key
            )
        })

        it('backs the report with one piece of evidence per failing tool', () => {
            assert.deepEqual(
                signalReport(NOW, SURVEYS, []).evidence.map((entry) => entry.source_id),
                ['survey-get']
            )
        })

        it('renders diagnostic punctuation literally in the inbox report', () => {
            const items = [{ ...TOOL, topError: 'Invalid value for `format`\nExpected [json]' }]
            const { summary } = signalReport(NOW, { ...SURVEYS, items }, [])
            assert.ok(summary.includes('Top error: `` Invalid value for `format` Expected [json] ``'))
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

        it('files all 51 tools once across API-sized reports with stable weekly keys', async () => {
            const items = Array.from({ length: 51 }, (_, i) => ({
                ...TOOL,
                tool: `survey-tool-${String(i).padStart(2, '0')}`,
            }))
            const byKey = new Map()
            const replay = async (now) =>
                fileTeamSignals([{ ...SURVEYS, items }], {
                    now,
                    membersOf: async () => ['reviewer'],
                    file: async (body) => {
                        if (body.evidence.length > 50) {
                            throw new Error('Signals accepts at most 50 evidence items')
                        }
                        byKey.set(
                            body.idempotency_key,
                            body.evidence.map(({ source_id }) => source_id)
                        )
                        return { report_id: body.idempotency_key }
                    },
                })
            await replay(NOW)
            await replay(new Date('2026-10-29T09:00:00Z'))
            assert.deepEqual([...byKey.values()], [items.slice(0, 50).map(({ tool }) => tool), [items[50].tool]])
        })

        it('keeps the summary under the API limit without dropping evidence', () => {
            const items = Array.from({ length: 50 }, (_, index) => ({
                ...TOOL,
                tool: `survey-tool-${index}-${'long-name-'.repeat(6)}`,
                topError: 'x'.repeat(160),
            }))
            const report = signalReport(NOW, { ...SURVEYS, items }, [])
            assert.deepEqual([report.summary.length <= 20000, report.evidence.length], [true, 50])
        })

        it('keeps filing a team’s other reports when one part fails', async () => {
            const items = Array.from({ length: 51 }, (_, i) => ({ ...TOOL, tool: `survey-tool-${i}` }))
            const reports = await fileTeamSignals([{ ...SURVEYS, items }], {
                now: NOW,
                membersOf: async () => ['reviewer'],
                file: async (body) => {
                    if (body.evidence.length !== 1) {
                        throw new Error('503')
                    }
                    return { report_id: 'second-part' }
                },
            })
            assert.deepEqual(reports, [{ owner: SURVEYS.owner, reportId: 'second-part' }])
        })

        it('reuses the same evidence batches when a partial retry changes the ranking', async () => {
            const tools = Array.from({ length: 51 }, (_, i) => ({
                ...TOOL,
                tool: `tool-${String(i).padStart(2, '0')}`,
            }))
            const byKey = new Map()
            const file = async (body) => {
                const existing = byKey.get(body.idempotency_key)
                if (existing) {
                    return { report_id: body.idempotency_key, idempotent_replay: true }
                }
                if (byKey.size === 0 && body.evidence.length === 50) {
                    throw new Error('503')
                }
                byKey.set(
                    body.idempotency_key,
                    body.evidence.map(({ source_id }) => source_id)
                )
                return { report_id: body.idempotency_key }
            }
            const options = { now: NOW, membersOf: async () => ['reviewer'], file }
            await fileTeamSignals([{ ...SURVEYS, items: tools }], options)
            await fileTeamSignals([{ ...SURVEYS, items: [tools.at(-1), ...tools.slice(0, -1)] }], options)
            assert.deepEqual(
                [...byKey.values()].flat().sort(),
                tools.map(({ tool }) => tool)
            )
        })

        it('counts only new Signals reports against the per-run filing budget', async () => {
            const teams = Array.from({ length: 22 }, (_, i) => ({ ...SURVEYS, owner: `team-${i}` }))
            const attempts = []
            await fileTeamSignals(teams, {
                now: NOW,
                membersOf: async () => ['reviewer'],
                file: async (body) => {
                    const idempotent_replay = attempts.length === 0
                    attempts.push(body.idempotency_key)
                    return { report_id: body.idempotency_key, idempotent_replay }
                },
            })
            assert.equal(attempts.length, 21)
        })

        it('offers each team its first report before filing overflow parts', async () => {
            const items = Array.from({ length: 51 }, (_, i) => ({ ...TOOL, tool: `tool-${i}` }))
            const owners = []
            await fileTeamSignals(
                [
                    { ...SURVEYS, items },
                    { ...SURVEYS, owner: 'team-other' },
                ],
                {
                    now: NOW,
                    membersOf: async () => ['reviewer'],
                    file: async (body) => {
                        owners.push(body.tags[1])
                        return { report_id: body.idempotency_key }
                    },
                }
            )
            assert.deepEqual(owners, ['team-surveys', 'team-other', 'team-surveys'])
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
