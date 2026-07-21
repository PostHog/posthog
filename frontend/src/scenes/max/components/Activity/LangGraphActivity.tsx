import React from 'react'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet/CodeSnippet'

import { TaskExecutionStatus as ExecutionStatus } from '~/queries/schema/schema-assistant-messages'

import { Activity, ActivityToggleSection, MarkdownMessage } from 'products/posthog_ai/frontend/api/primitives'

import type { EnhancedToolCall } from '../../max-constants'
import { SummarizeSessionsWidget, UIPayloadAnswer, isRenderableUIPayloadTool } from '../../messages/UIPayloadAnswer'

export function LangGraphActivity({
    id,
    content,
    substeps,
    state,
    icon,
    animate = true,
    showCompletionIcon = true,
    widget = null,
    toolCall = null,
}: {
    id: string
    content: string
    // actually a markdown message
    substeps: string[]
    state: ExecutionStatus
    icon?: React.ReactNode
    animate?: boolean
    showCompletionIcon?: boolean
    widget?: JSX.Element | null
    toolCall?: EnhancedToolCall | null
}): JSX.Element {
    const result = toolCall?.result
    const resultContent = result?.content
    const uiPayload = result?.ui_payload
    const executedSQLQuery =
        typeof uiPayload?.execute_sql === 'string'
            ? uiPayload.execute_sql
            : toolCall?.name === 'execute_sql' && typeof toolCall.args.query === 'string'
              ? toolCall.args.query
              : null

    const uiPayloadBody =
        toolCall && uiPayload && isRenderableUIPayloadTool(toolCall.name, uiPayload)
            ? Object.entries(uiPayload)
                  .filter(
                      ([toolName]) => toolName !== 'summarize_sessions' && toolName !== 'summarize_website_interactions'
                  )
                  .map(([toolName, toolPayload]) => (
                      <UIPayloadAnswer
                          key={`${result?.tool_call_id}-${toolName}`}
                          toolCallId={result!.tool_call_id}
                          toolName={toolName}
                          toolPayload={toolPayload}
                          embedded
                      />
                  ))
            : []

    const activityChildren = (
        <>
            {widget}
            {/* Render summarize_sessions UI payload outside details so "Open report" is always visible. */}
            {!!uiPayload?.summarize_sessions && result && (
                <SummarizeSessionsWidget
                    payload={uiPayload.summarize_sessions}
                    title={toolCall?.args.summary_title as string | undefined}
                />
            )}
            {!!uiPayload?.summarize_website_interactions && result && (
                <UIPayloadAnswer
                    toolCallId={result.tool_call_id}
                    toolName="summarize_website_interactions"
                    toolPayload={uiPayload.summarize_website_interactions}
                    embedded
                />
            )}
        </>
    )

    // The tool call's details — UI payload, SQL, args, and result — live behind the chevron and only
    // surface once the call has produced a result. An in-flight call shows just the shimmering title,
    // with no expandable child.
    const details =
        toolCall && resultContent ? (
            <div className="flex flex-col gap-1">
                {uiPayloadBody.length > 0 && <div className="flex flex-col gap-2">{uiPayloadBody}</div>}
                {executedSQLQuery && (
                    <div className="flex flex-col gap-1">
                        <b className="text-secondary">SQL query</b>
                        <CodeSnippet language={Language.SQL} className="text-xs" compact>
                            {executedSQLQuery}
                        </CodeSnippet>
                    </div>
                )}
                <ActivityToggleSection
                    title="Tool called:"
                    summary={<span>{toolCall.name}</span>}
                    tooltip="Tool call arguments as JSON"
                >
                    <CodeSnippet language={Language.JSON} className="text-xs">
                        {JSON.stringify(toolCall.args, null, 2)}
                    </CodeSnippet>
                </ActivityToggleSection>
                <ActivityToggleSection
                    title="Tool result:"
                    summary={<span>{resultContent.slice(0, 20)}...</span>}
                    tooltip="Show tool call results"
                >
                    <div className="border rounded p-2 bg-surface-primary">
                        <MarkdownMessage
                            id={`${toolCall.id}-result`}
                            content={resultContent}
                            className="text-xs [&_code]:text-xs"
                        />
                    </div>
                </ActivityToggleSection>
            </div>
        ) : null

    return (
        <Activity
            id={id}
            title={<MarkdownMessage id={id} content={content} />}
            substeps={substeps}
            status={state}
            icon={icon}
            animate={animate}
            showCompletionIcon={showCompletionIcon}
            details={details}
        >
            {activityChildren}
        </Activity>
    )
}
