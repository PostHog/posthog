import { LLMTrace, LLMTraceEvent } from '~/queries/schema'

import {
    AnthropicInputMessage,
    AnthropicTextMessage,
    AnthropicToolCallMessage,
    CompatMessage,
    CompatToolCall,
    OpenAICompletionMessage,
    OpenAIToolCall,
} from './types'

function formatUsage(inputTokens: number, outputTokens?: number | null): string | null {
    return `${inputTokens} → ${outputTokens || 0} (∑ ${inputTokens + (outputTokens || 0)})`
}

export function formatLLMUsage(trace_or_event: LLMTrace | LLMTraceEvent): string | null {
    if ('properties' in trace_or_event && typeof trace_or_event.properties.$ai_input_tokens === 'number') {
        return formatUsage(trace_or_event.properties.$ai_input_tokens, trace_or_event.properties.$ai_output_tokens)
    }

    if (!('properties' in trace_or_event) && typeof trace_or_event.inputTokens === 'number') {
        return formatUsage(trace_or_event.inputTokens, trace_or_event.outputTokens)
    }

    return null
}

export function formatLLMLatency(latency: number): string {
    return `${Math.round(latency * 100) / 100} s`
}

const usdFormatter = new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 4,
})

export function formatLLMCost(cost: number): string {
    return usdFormatter.format(cost)
}

export function isOpenAICompatToolCall(input: unknown): input is OpenAIToolCall {
    return (
        input !== null &&
        typeof input === 'object' &&
        'type' in input &&
        'function' in input &&
        input.type === 'function' &&
        typeof input.function === 'object' &&
        input.function !== null
    )
}

export function isOpenAICompatToolCallsArray(input: any): input is OpenAIToolCall[] {
    return Array.isArray(input) && input.every(isOpenAICompatToolCall)
}

export function isOpenAICompatMessage(output: unknown): output is OpenAICompletionMessage {
    return !!output && typeof output === 'object' && 'role' in output && 'content' in output
}

export function parseOpenAIToolCalls(toolCalls: OpenAIToolCall[]): CompatToolCall[] {
    const toolsWithParsedArguments = toolCalls.map((toolCall) => ({
        ...toolCall,
        function: {
            ...toolCall.function,
            arguments:
                typeof toolCall.function.arguments === 'string'
                    ? JSON.parse(toolCall.function.arguments)
                    : toolCall.function.arguments,
        },
    }))

    return toolsWithParsedArguments
}

export function isAnthropicTextMessage(output: unknown): output is AnthropicTextMessage {
    return !!output && typeof output === 'object' && 'type' in output && output.type === 'text'
}

export function isAnthropicToolCallMessage(output: unknown): output is AnthropicToolCallMessage {
    return !!output && typeof output === 'object' && 'type' in output && output.type === 'tool_use'
}

export function isAnthropicRoleBasedMessage(input: unknown): input is AnthropicInputMessage {
    return !!input && typeof input === 'object' && 'role' in input && 'content' in input
}

export function normalizeOutputMessage(output: unknown): CompatMessage[] {
    // OpenAI
    if (isOpenAICompatMessage(output)) {
        return [
            {
                ...output,
                role: output.role,
                content: output.content,
                tool_calls: isOpenAICompatToolCallsArray(output.tool_calls)
                    ? parseOpenAIToolCalls(output.tool_calls)
                    : undefined,
            },
        ]
    }

    // Anthropic
    // Normal completion
    if (isAnthropicTextMessage(output)) {
        return [
            {
                ...output,
                role: 'assistant',
                content: output.text,
            },
        ]
    }

    // Tool call completion
    if (isAnthropicToolCallMessage(output)) {
        return [
            {
                ...output,
                role: 'assistant',
                content: '',
                tool_calls: [
                    {
                        type: 'function',
                        id: output.id,
                        function: {
                            name: output.name,
                            arguments: output.input,
                        },
                    },
                ],
            },
        ]
    }

    // Input message
    if (isAnthropicRoleBasedMessage(output)) {
        // Content is a nested array (tool responses, etc.)
        if (Array.isArray(output.content)) {
            return output.content.map(normalizeOutputMessage).flat()
        }

        return [
            {
                ...output,
                role: output.role,
                content: output.content,
            },
        ]
    }

    // Unsupported message.
    return [
        {
            role: 'assistant',
            content: typeof output === 'string' ? output : JSON.stringify(output),
        },
    ]
}

export function normalizeMessages(output: unknown): CompatMessage[] | null {
    if (!output) {
        return null
    }

    if (Array.isArray(output)) {
        return output.map(normalizeOutputMessage).flat()
    }

    if (typeof output === 'object' && 'choices' in output && Array.isArray(output.choices)) {
        return output.choices.map(normalizeOutputMessage).flat()
    }

    return null
}
