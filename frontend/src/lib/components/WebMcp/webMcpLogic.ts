import { actions, afterMount, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { McpToolDefinition, McpToolResult } from '~/types'

import type { webMcpLogicType } from './webMcpLogicType'

export interface WebMcpLogicProps {
    key: string
}

export const webMcpLogic = kea<webMcpLogicType>([
    path(['lib', 'components', 'WebMcp', 'webMcpLogic']),
    props({} as WebMcpLogicProps),
    key((props) => props.key),

    actions({
        invokeTool: (toolName: string, args: Record<string, any>) => ({ toolName, args }),
        setToolResult: (toolName: string, result: McpToolResult) => ({ toolName, result }),
        clearToolResult: (toolName: string) => ({ toolName }),
    }),

    loaders({
        tools: {
            __default: [] as McpToolDefinition[],
            loadTools: async (): Promise<McpToolDefinition[]> => {
                return await api.mcpTools.list()
            },
        },
    }),

    reducers({
        toolResults: [
            {} as Record<string, McpToolResult>,
            {
                setToolResult: (state, { toolName, result }) => ({ ...state, [toolName]: result }),
                clearToolResult: (state, { toolName }) => {
                    const next = { ...state }
                    delete next[toolName]
                    return next
                },
            },
        ],
        activeInvocations: [
            {} as Record<string, boolean>,
            {
                invokeTool: (state, { toolName }) => ({ ...state, [toolName]: true }),
                setToolResult: (state, { toolName }) => ({ ...state, [toolName]: false }),
            },
        ],
    }),

    selectors({
        toolsByName: [
            (s) => [s.tools],
            (tools): Record<string, McpToolDefinition> => Object.fromEntries(tools.map((t) => [t.name, t])),
        ],
        isInvoking: [
            (s) => [s.activeInvocations],
            (activeInvocations): ((toolName: string) => boolean) =>
                (toolName: string) =>
                    !!activeInvocations[toolName],
        ],
    }),

    listeners(({ actions }) => ({
        invokeTool: async ({ toolName, args }) => {
            try {
                const result = await api.mcpTools.invoke(toolName, args)
                actions.setToolResult(toolName, result)
                if (!result.success) {
                    lemonToast.error(`Tool '${toolName}' failed: ${result.content}`)
                }
            } catch (e: any) {
                actions.setToolResult(toolName, {
                    success: false,
                    content: e.message || 'An unexpected error occurred',
                })
                lemonToast.error(`Failed to invoke tool '${toolName}'`)
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadTools()
    }),
])
