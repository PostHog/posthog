import { IconPerson } from '@posthog/icons'

import { JSONViewer } from 'lib/components/JSONViewer'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { IconExclamation, IconRobot } from 'lib/lemon-ui/icons'
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

const isHumanMessage = (message: Record<string, any>): boolean => {
    return message.type === 'human' || message.role === 'user' || message.role === 'human'
}

const isAIMessage = (message: Record<string, any>): boolean => {
    return (
        (message.type === 'ai' || message.role === 'assistant' || message.role === 'ai') &&
        !!message.content?.length &&
        message.visible !== false
    )
}

const isDisplayableAIMessage = (message: Record<string, any>): boolean => {
    return isHumanMessage(message) || isAIMessage(message)
}

export function AIEventSummary({ event }: { event: Record<string, any> }): JSX.Element | null {
    const showConversation = useFeatureFlag('REPLAY_X_LLM_ANALYTICS_CONVERSATION_VIEW')

    if (event.properties.$ai_is_error) {
        return (
            <div className="flex items-center gap-1 text-danger">
                <IconExclamation />
                <span>Error</span>
            </div>
        )
    }

    if (!showConversation) {
        return null
    }

    const inputMessages = (
        (event.properties?.$ai_input_state?.messages as Record<string, any>[] | undefined) ??
        (event.properties?.$ai_input as Record<string, any>[] | undefined) ??
        []
    ).filter(isDisplayableAIMessage)
    const outputMessages = (
        (event.properties?.$ai_output_state?.messages as Record<string, any>[] | undefined) ??
        (event.properties?.$ai_output_choices as Record<string, any>[] | undefined) ??
        []
    ).filter(isDisplayableAIMessage)
    const seen = new Set<string>()
    const messageChain: Array<{ id: string; content: string; role: string }> = []

    for (const m of [...inputMessages, ...outputMessages]) {
        if (typeof m.content !== 'string') {
            continue
        }

        const role = m.role && !m.type ? (m.role === 'user' ? 'human' : 'ai') : m.type
        const key = `${role}:${m.content}`

        if (!seen.has(key)) {
            seen.add(key)
            messageChain.push({ id: m.id, content: m.content, role })
        }
    }

    return (
        <div className="hidden @sm:flex flex-col items-center gap-1 text-muted-alt">
            {messageChain.map((m) => (
                <div
                    className={cn(
                        'flex flex-row w-full items-center',
                        isHumanMessage(m) ? 'justify-end' : 'justify-start'
                    )}
                    key={m.id}
                >
                    {isAIMessage(m) && <IconRobot className="mr-1 text-2xl" />}
                    <div className="max-w-2/3 border rounded px-2 py-1 text-wrap text-sm bg-surface-primary">
                        {m.content}
                    </div>
                    {isHumanMessage(m) && <IconPerson className="ml-1 text-2xl" />}
                </div>
            ))}
        </div>
    )
}
