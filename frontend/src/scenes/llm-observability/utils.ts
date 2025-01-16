import { LLMGeneration, LLMTrace } from '~/queries/schema'

export function formatLLMUsage(trace: LLMTrace | LLMGeneration): string | null {
    if (typeof trace.inputTokens === 'number') {
        return `${trace.inputTokens} → ${trace.outputTokens || 0} (∑ ${trace.inputTokens + (trace.outputTokens || 0)})`
    }

    return null
}

export function formatLLMLatency(latency: number): string {
    return `${Math.round(latency * 100) / 100}s`
}

const numberFormatter = new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 4,
})

export function formatLLMCost(cost: number): string {
    return numberFormatter.format(cost)
}

export interface RoleBasedMessage {
    role: string
    content: string
    additional_kwargs?: any
    tool_calls?: any
}

export function isRoleBasedMessage(input: any): input is RoleBasedMessage {
    return (
        typeof input === 'object' &&
        'role' in input &&
        'content' in input &&
        typeof input.role === 'string' &&
        typeof input.content === 'string'
    )
}

export interface ChoicesOutput {
    choices: RoleBasedMessage[]
}

export function isChoicesOutput(input: any): input is ChoicesOutput {
    return typeof input === 'object' && 'choices' in input && Array.isArray(input.choices)
}

export interface ToolCall {
    type: string
    id?: string
    function: {
        name: string
        arguments: string
    }
}

export function isToolCall(input: any): input is ToolCall {
    return typeof input === 'object' && 'type' in input && 'function' in input && input.type === 'function'
}

export type ToolCalls = ToolCall[]

export function isToolCallsArray(input: any): input is ToolCalls {
    return Array.isArray(input) && input.every(isToolCall)
}

export function formatToolCalls(toolCalls: ToolCalls): string {
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

    return JSON.stringify(toolsWithParsedArguments, null, 2)
}

export function formatAsMarkdownJSONBlock(output: string): string {
    return `\`\`\`json\n${output}\n\`\`\``
}
