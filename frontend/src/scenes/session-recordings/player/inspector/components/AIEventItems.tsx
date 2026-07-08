import { JSONViewer } from 'lib/components/JSONViewer'
import { IconExclamation } from 'lib/lemon-ui/icons'
import { cn } from 'lib/utils/css-classes'
import { isObject } from 'lib/utils/guards'

import { AIDataLoading } from 'products/ai_observability/frontend/components/AIDataLoading'
import { ConversationMessagesDisplay } from 'products/ai_observability/frontend/ConversationDisplay/ConversationMessagesDisplay'
import { useAIData } from 'products/ai_observability/frontend/hooks/useAIData'
import { LLMInputOutput } from 'products/ai_observability/frontend/LLMInputOutput'
import { normalizeMessages } from 'products/ai_observability/frontend/messageNormalization'

export function AIEventExpanded({ event }: { event: Record<string, any> }): JSX.Element {
    const { input, output, tools, isLoading } = useAIData({
        uuid: event.uuid,
        input: event.properties?.$ai_input,
        output: event.properties?.$ai_output_choices,
        tools: event.properties?.$ai_tools,
        traceId: event.properties?.$ai_trace_id,
        timestamp: event.timestamp,
    })

    const isGeneration = event.event === '$ai_generation'
    const raisedError = event.properties.$ai_is_error

    if (isLoading) {
        return <AIDataLoading variant="block" />
    }

    return (
        <div>
            {isGeneration ? (
                <ConversationMessagesDisplay
                    inputNormalized={normalizeMessages(input, 'user', tools).messages}
                    outputNormalized={normalizeMessages(output, 'assistant').messages}
                    errorData={event.properties.$ai_error}
                    httpStatus={event.properties.$ai_http_status}
                    raisedError={raisedError}
                    traceId={event.properties.$ai_trace_id}
                />
            ) : (
                <LLMInputOutput
                    inputDisplay={
                        <div className="p-2 text-xs border rounded bg-[var(--color-bg-fill-secondary)]">
                            {isObject(input) ? (
                                <JSONViewer src={input} collapsed={2} />
                            ) : (
                                <span className="font-mono">{JSON.stringify(input ?? null)}</span>
                            )}
                        </div>
                    }
                    outputDisplay={
                        <div
                            className={cn(
                                'p-2 text-xs border rounded',
                                !raisedError
                                    ? 'bg-[var(--color-bg-fill-success-tertiary)]'
                                    : 'bg-[var(--color-bg-fill-error-tertiary)]'
                            )}
                        >
                            {isObject(output) ? (
                                <JSONViewer src={output} collapsed={2} />
                            ) : (
                                <span className="font-mono">{JSON.stringify(output ?? null)}</span>
                            )}
                        </div>
                    }
                />
            )}
        </div>
    )
}

export function AIEventSummary({ event }: { event: Record<string, any> }): JSX.Element | null {
    if (event.properties.$ai_is_error) {
        return (
            <div className="flex items-center gap-1 text-danger">
                <IconExclamation />
                <span>Error</span>
            </div>
        )
    }

    return null
}
