/**
 * Extract tool call names from AI generation output choices.
 *
 * Handles multiple formats:
 * - OpenAI: messages with `tool_calls` array containing `{type: "function", function: {name: "..."}}`
 * - Anthropic: content items with `{type: "tool_use", name: "..."}`
 */

interface OpenAIToolCall {
    type?: string
    function?: {
        name?: string
    }
}

interface OpenAIChoice {
    message?: {
        tool_calls?: OpenAIToolCall[]
    }
}

interface AnthropicContentBlock {
    type?: string
    name?: string
}

interface AnthropicChoice {
    message?: {
        content?: AnthropicContentBlock[]
    }
}

type OutputChoice = OpenAIChoice | AnthropicChoice

function extractFromOpenAIToolCalls(toolCalls: unknown[]): string[] {
    const names: string[] = []
    for (const call of toolCalls) {
        if (typeof call === 'object' && call !== null) {
            const tc = call as OpenAIToolCall
            if (tc.function?.name && typeof tc.function.name === 'string') {
                names.push(tc.function.name)
            }
        }
    }
    return names
}

function extractFromAnthropicContent(content: unknown[]): string[] {
    const names: string[] = []
    for (const block of content) {
        if (typeof block === 'object' && block !== null) {
            const cb = block as AnthropicContentBlock
            if (cb.type === 'tool_use' && cb.name && typeof cb.name === 'string') {
                names.push(cb.name)
            }
        }
    }
    return names
}

/**
 * Extract tool call names from output choices in call order.
 * Returns an empty array if no tool calls are found or data is malformed.
 */
export function extractToolCallNames(outputChoices: unknown): string[] {
    if (!Array.isArray(outputChoices)) {
        return []
    }

    const names: string[] = []

    for (const choice of outputChoices) {
        if (typeof choice !== 'object' || choice === null) {
            continue
        }

        const c = choice as OutputChoice
        const message = c.message

        if (typeof message !== 'object' || message === null) {
            continue
        }

        // OpenAI format: message.tool_calls
        if ('tool_calls' in message && Array.isArray(message.tool_calls)) {
            names.push(...extractFromOpenAIToolCalls(message.tool_calls))
        }

        // Anthropic format: message.content with tool_use blocks
        if ('content' in message && Array.isArray(message.content)) {
            names.push(...extractFromAnthropicContent(message.content))
        }
    }

    return names
}
