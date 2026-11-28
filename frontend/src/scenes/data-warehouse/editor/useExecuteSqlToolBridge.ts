import { useActions, useValues } from 'kea'
import { useCallback, useMemo, useRef } from 'react'

import { useDebouncedValue } from 'lib/hooks/useDebouncedValue'
import { UseMaxToolOptions } from 'scenes/max/useMaxTool'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'

import { useAttachedContext, useMcpToolApplyBack } from 'products/posthog_ai/frontend/api/logics'

import { applyExecuteSqlToolOutput, getExecuteSqlToolContext } from './maxSqlTool'
import { sqlEditorLogic } from './sqlEditorLogic'

const EMBEDDED_MAX_TOOL_CONTEXT_DEBOUNCE_MS = 150

/**
 * Connects the editor to PostHog AI's execute-sql tool: it attaches the current query as context,
 * applies the tool's answers back into the editor, and returns the props for a button that opens
 * the tool. Shared by the Lemon query window and the quill workspace.
 */
export function useExecuteSqlToolBridge(tabId: string, active: boolean): Omit<UseMaxToolOptions, 'active'> {
    const { queryInput, sourceQuery } = useValues(sqlEditorLogic)
    const { setSourceQuery, setSuggestedQueryInput, reportAIQueryPromptOpen } = useActions(sqlEditorLogic)

    const debouncedMaxToolQueryInput = useDebouncedValue(queryInput, EMBEDDED_MAX_TOOL_CONTEXT_DEBOUNCE_MS)
    const debouncedMaxToolSourceQuery = useDebouncedValue(sourceQuery, EMBEDDED_MAX_TOOL_CONTEXT_DEBOUNCE_MS)
    const executeSqlToolStateRef = useRef({ queryInput, sourceQuery })
    executeSqlToolStateRef.current = { queryInput, sourceQuery }
    const executeSqlToolContext = useMemo(
        () => getExecuteSqlToolContext(debouncedMaxToolQueryInput, debouncedMaxToolSourceQuery),
        [debouncedMaxToolQueryInput, debouncedMaxToolSourceQuery]
    )

    const attachedContextItems = useMemo(
        () => [
            { type: 'sql_editor_state' as const, value: JSON.stringify(executeSqlToolContext), label: 'Current query' },
        ],
        [executeSqlToolContext]
    )
    useAttachedContext(attachedContextItems, { active })

    const executeSqlToolContextDescription = useMemo(
        () => ({
            text: 'Current query',
            icon: iconForType('sql_editor'),
        }),
        []
    )
    const executeSqlToolIntroOverride = useMemo(
        () => ({
            headline: 'What data do you want to analyze?',
            description: 'Let me help you quickly write SQL, and tweak it.',
        }),
        []
    )
    const executeSqlToolSuggestions = useMemo(() => [], [])
    const handleExecuteSqlToolOutput = useCallback(
        (toolOutput: unknown) => {
            const { queryInput, sourceQuery } = executeSqlToolStateRef.current
            applyExecuteSqlToolOutput({
                toolOutput,
                queryInput,
                sourceQuery,
                setSourceQuery,
                setSuggestedQueryInput,
            })
        },
        [setSourceQuery, setSuggestedQueryInput]
    )
    const executeSqlMaxToolProps = useMemo(
        () => ({
            identifier: 'execute_sql' as const,
            context: executeSqlToolContext,
            contextDescription: executeSqlToolContextDescription,
            callback: handleExecuteSqlToolOutput,
            suggestions: executeSqlToolSuggestions,
            onMaxOpen: reportAIQueryPromptOpen,
            introOverride: executeSqlToolIntroOverride,
        }),
        [
            executeSqlToolContext,
            executeSqlToolContextDescription,
            executeSqlToolIntroOverride,
            executeSqlToolSuggestions,
            handleExecuteSqlToolOutput,
            reportAIQueryPromptOpen,
        ]
    )
    // Sandbox-runtime apply-back for the same tool the legacy MaxTool callback above handles. Reuses
    // that callback verbatim so the diff-mode gate and filters handling stay shared with legacy.
    useMcpToolApplyBack({
        tools: ['execute-sql'],
        targetKey: `sql:${tabId}`,
        active,
        onApply: (_event, { innerInput }) => {
            if (!active || !innerInput) {
                return
            }
            handleExecuteSqlToolOutput(innerInput)
        },
    })

    return executeSqlMaxToolProps
}
