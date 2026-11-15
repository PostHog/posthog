import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import {
    definitionPathFor,
    fetchFailingTools,
    HANDWRITTEN_TOOL_PATH,
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
})
