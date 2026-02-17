import { useActions, useValues } from 'kea'
import { useCallback } from 'react'

import { McpToolResult } from '~/types'

import { webMcpLogic } from './webMcpLogic'

interface UseWebMcpToolReturn {
    invoke: (args: Record<string, any>) => void
    result: McpToolResult | undefined
    isLoading: boolean
    clear: () => void
}

export function useWebMcpTool(toolName: string): UseWebMcpToolReturn {
    const logic = webMcpLogic({ key: 'global' })
    const { toolResults, activeInvocations } = useValues(logic)
    const { invokeTool, clearToolResult } = useActions(logic)

    const invoke = useCallback((args: Record<string, any>) => invokeTool(toolName, args), [toolName, invokeTool])

    const clear = useCallback(() => clearToolResult(toolName), [toolName, clearToolResult])

    return {
        invoke,
        result: toolResults[toolName],
        isLoading: !!activeInvocations[toolName],
        clear,
    }
}
