import { isObject } from 'lib/utils/guards'

import type { Message } from './llmPlaygroundPromptsLogic'

export interface ProviderMessage {
    role: 'user' | 'assistant'
    content: string | Record<string, unknown>[]
}

/** A message earns a slot in the request when it carries text, tool calls, or a tool result. */
export function isMessageSendable(message: Message): boolean {
    return message.content.trim().length > 0 || !!message.toolCalls?.length || message.role === 'tool'
}

// Arguments that do not parse to an object are passed through as the raw string, so the
// backend rejects them with a message naming the tool instead of silently sending {}.
function parseToolCallArguments(args: string): unknown {
    if (!args.trim()) {
        return {}
    }
    try {
        const parsed = JSON.parse(args)
        return isObject(parsed) ? parsed : args
    } catch {
        return args
    }
}

function isToolResultOnlyMessage(message: ProviderMessage): boolean {
    return (
        message.role === 'user' &&
        Array.isArray(message.content) &&
        message.content.every((block) => isObject(block) && block.type === 'tool_result')
    )
}

/**
 * Maps playground messages to the proxy's provider-neutral wire shape: Anthropic-style
 * content blocks. Assistant tool calls become `tool_use` blocks; tool messages become
 * user-role turns of `tool_result` blocks. Consecutive tool messages merge into one user
 * turn, because Anthropic requires every result for a turn in the single next user message.
 * The provider adapters absorb the per-provider differences from there.
 */
export function toProviderMessages(messages: Message[]): ProviderMessage[] {
    const result: ProviderMessage[] = []
    for (const message of messages) {
        if (message.role === 'system') {
            continue
        }
        if (message.role === 'tool') {
            const block: Record<string, unknown> = {
                type: 'tool_result',
                tool_use_id: message.toolCallId ?? '',
                content: message.content,
            }
            const previous = result[result.length - 1]
            if (previous && isToolResultOnlyMessage(previous)) {
                ;(previous.content as Record<string, unknown>[]).push(block)
            } else {
                result.push({ role: 'user', content: [block] })
            }
            continue
        }
        if (message.role === 'assistant' && message.toolCalls?.length) {
            const content: Record<string, unknown>[] = []
            if (message.content.trim()) {
                content.push({ type: 'text', text: message.content })
            }
            for (const toolCall of message.toolCalls) {
                content.push({
                    type: 'tool_use',
                    id: toolCall.id,
                    name: toolCall.name,
                    input: parseToolCallArguments(toolCall.arguments),
                })
            }
            result.push({ role: 'assistant', content })
            continue
        }
        result.push({ role: message.role, content: message.content })
    }
    return result
}
