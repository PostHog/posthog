import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { McpToolDefinition } from '~/types'

import { webMcpLogic } from './webMcpLogic'

const MOCK_TOOLS: McpToolDefinition[] = [
    {
        name: 'execute_sql',
        scopes: ['query:read'],
        input_schema: {
            type: 'object',
            properties: {
                query: { type: 'string', description: 'The SQL query to execute' },
            },
            required: ['query'],
        },
    },
    {
        name: 'read_taxonomy',
        scopes: ['event_definition:read'],
        input_schema: {
            type: 'object',
            properties: {
                entity_type: { type: 'string', description: 'Type of entity' },
            },
            required: ['entity_type'],
        },
    },
]

describe('webMcpLogic', () => {
    let logic: ReturnType<typeof webMcpLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/mcp_tools/': MOCK_TOOLS,
            },
            post: {
                '/api/environments/:team_id/mcp_tools/:tool_name/': {
                    success: true,
                    content: 'query result',
                },
            },
        })
        initKeaTests()
        logic = webMcpLogic({ key: 'test' })
        logic.mount()
    })

    it('loads tools on mount', async () => {
        await expectLogic(logic).toFinishAllListeners()

        await expectLogic(logic).toMatchValues({
            tools: MOCK_TOOLS,
            toolsLoading: false,
        })
    })

    it('builds toolsByName selector', async () => {
        await expectLogic(logic).toFinishAllListeners()

        await expectLogic(logic).toMatchValues({
            toolsByName: {
                execute_sql: MOCK_TOOLS[0],
                read_taxonomy: MOCK_TOOLS[1],
            },
        })
    })

    it('invokes a tool and stores result', async () => {
        await expectLogic(logic).toFinishAllListeners()

        await expectLogic(logic, () => {
            logic.actions.invokeTool('execute_sql', { query: 'SELECT 1' })
        }).toFinishAllListeners()

        await expectLogic(logic).toMatchValues({
            toolResults: {
                execute_sql: { success: true, content: 'query result' },
            },
        })
    })

    it('sets activeInvocations while a tool is running', async () => {
        await expectLogic(logic).toFinishAllListeners()

        await expectLogic(logic, () => {
            logic.actions.invokeTool('execute_sql', { query: 'SELECT 1' })
        }).toDispatchActions(['invokeTool'])

        expect(logic.values.activeInvocations['execute_sql']).toBe(true)

        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.activeInvocations['execute_sql']).toBe(false)
    })

    it('clears tool result', async () => {
        await expectLogic(logic).toFinishAllListeners()

        await expectLogic(logic, () => {
            logic.actions.invokeTool('execute_sql', { query: 'SELECT 1' })
        }).toFinishAllListeners()

        expect(logic.values.toolResults['execute_sql']).toBeTruthy()

        await expectLogic(logic, () => {
            logic.actions.clearToolResult('execute_sql')
        })

        expect(logic.values.toolResults['execute_sql']).toBeUndefined()
    })
})
