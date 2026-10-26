import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import {
    definitionPathFor,
    deliverTeamDigests,
    fetchFailingTools,
    HANDWRITTEN_TOOL_PATH,
    toolDefinitionIndex,
} from './weekly-mcp-tool-health-report.mjs'
import { resolveOwners } from './weekly-report-common.mjs'

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

const TEAM = { owner: 'team-surveys', channel: '#team-surveys', rows: [['row']] }

function recordingSlack({ failChannelPosts = false } = {}) {
    const posts = []
    return {
        posts,
        slack: {
            post: async (blocks, text, options) => {
                if (failChannelPosts && options.channel) {
                    throw new Error('not_in_channel')
                }
                posts.push(options)
                return { ts: '2.0' }
            },
            pause: async () => {},
        },
    }
}

describe('weekly MCP tool health report', () => {
    it('maps tools and wrappers to their definition file and nothing else', () => {
        const index = toolDefinitionIndex({
            listFiles: () => ['products/surveys/mcp/tools.yaml'],
            readFile: () => DEFINITION,
        })
        assert.deepEqual(
            [...index.entries()],
            [
                ['survey-create', 'products/surveys/mcp/tools.yaml'],
                ['survey-get', 'products/surveys/mcp/tools.yaml'],
                ['survey-delete-prepare', 'products/surveys/mcp/tools.yaml'],
                ['survey-delete-execute', 'products/surveys/mcp/tools.yaml'],
                ['query-survey', 'products/surveys/mcp/tools.yaml'],
            ]
        )
        assert.equal(definitionPathFor('external-data-sources-db-schema', index), HANDWRITTEN_TOOL_PATH)
    })

    it('resolves owners for the report producer through owners.yaml', () => {
        const items = [{ selector: 'products/cdp/mcp/cdp_functions.yaml' }, { selector: HANDWRITTEN_TOOL_PATH }]
        const ownerFor = resolveOwners(items, (path) => [path], 'mcp_tool_health')
        assert.deepEqual(
            items.map((item) => ownerFor(item).owner),
            ['team-workflows', 'team-context-and-mcp']
        )
    })

    it('reads query rows into tool records', async () => {
        const tools = await fetchFailingTools(async () => ({
            results: [['survey-get', '120', '30', '7', null]],
        }))
        assert.deepEqual(tools, [{ tool: 'survey-get', calls: 120, errors: 30, users: 7, topError: '' }])
    })

    for (const { label, enabled, failChannelPosts, expected } of [
        {
            label: 'keeps every slice in the thread while team posts are off',
            enabled: false,
            failChannelPosts: false,
            expected: [{ threadTs: '1.0' }],
        },
        {
            label: 'posts a slice to its team channel when team posts are on',
            enabled: true,
            failChannelPosts: false,
            expected: [{ channel: '#team-surveys' }],
        },
        {
            label: 'falls back to the thread when the team channel rejects the post',
            enabled: true,
            failChannelPosts: true,
            expected: [{ threadTs: '1.0' }],
        },
    ]) {
        it(label, async () => {
            const { posts, slack } = recordingSlack({ failChannelPosts })
            await deliverTeamDigests([TEAM], {
                now: new Date('2026-10-26T00:00:00Z'),
                digest: { ts: '1.0' },
                enabled,
                slack,
            })
            assert.deepEqual(posts, expected)
        })
    }
})
