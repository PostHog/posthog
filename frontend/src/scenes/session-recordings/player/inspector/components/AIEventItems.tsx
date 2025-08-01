import { JSONViewer } from 'lib/components/JSONViewer'
import { IconExclamation } from 'lib/lemon-ui/icons'
import { isObject } from 'lib/utils'
import { cn } from 'lib/utils/css-classes'
import { ConversationMessagesDisplay } from 'products/llm_observability/frontend/ConversationDisplay/ConversationMessagesDisplay'
import { LLMInputOutput } from 'products/llm_observability/frontend/LLMInputOutput'
import { normalizeMessages } from 'products/llm_observability/frontend/utils'

export function AIEventExpanded({ event }: { event: Record<string, any> }): JSX.Element {
    let input = event.properties.$ai_input_state
    let output = event.properties.$ai_output_state ?? event.properties.$ai_error
    let raisedError = event.properties.$ai_is_error
    if (event.event === '$ai_generation') {
        input = event.properties.$ai_input
        output = event.properties.$ai_output_choices ?? event.properties.$ai_output
        raisedError = event.properties.$ai_is_error
    }
    return (
        <div>
            {event.event === '$ai_generation' ? (
                <ConversationMessagesDisplay
                    inputNormalized={normalizeMessages(event.properties.$ai_input, 'user', event.properties.$ai_tools)}
                    outputNormalized={normalizeMessages(
                        event.properties.$ai_is_error
                            ? event.properties.$ai_error
                            : event.properties.$ai_output_choices ?? event.properties.$ai_output,
                        'assistant'
                    )}
                    output={
                        event.properties.$ai_is_error
                            ? event.properties.$ai_error
                            : event.properties.$ai_output_choices ?? event.properties.$ai_output
                    }
                    httpStatus={event.properties.$ai_http_status}
                    raisedError={event.properties.$ai_is_error}
                />
            ) : (
                <LLMInputOutput
                    inputDisplay={
                        <div className="p-2 text-xs border rounded bg-[var(--bg-fill-secondary)]">
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
                                    ? 'bg-[var(--bg-fill-success-tertiary)]'
                                    : 'bg-[var(--bg-fill-error-tertiary)]'
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
