import { JSONViewer } from 'lib/components/JSONViewer'
import { isObject } from 'lib/utils'
import { cn } from 'lib/utils/css-classes'

import { ConversationMessagesDisplay } from 'products/llm_analytics/frontend/ConversationDisplay/ConversationMessagesDisplay'
import { LLMInputOutput } from 'products/llm_analytics/frontend/LLMInputOutput'
import { AIDataLoading } from 'products/llm_analytics/frontend/components/AIDataLoading'
import { useAIData } from 'products/llm_analytics/frontend/hooks/useAIData'
import { normalizeMessages } from 'products/llm_analytics/frontend/utils'

export function AIEventExpanded({ event }: { event: Record<string, any> }): JSX.Element {
    const { input, output, isLoading } = useAIData({
        uuid: event.uuid,
        input: event.properties?.$ai_input,
        output: event.properties?.$ai_output_choices,
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
                    inputNormalized={normalizeMessages(input, 'user', event.properties.$ai_tools)}
                    outputNormalized={normalizeMessages(output, 'assistant')}
                    errorData={event.properties.$ai_error}
                    httpStatus={event.properties.$ai_http_status}
                    raisedError={raisedError}
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
