import type { WorkOptionApi } from 'products/today/frontend/generated/api.schemas'

/** A fixed template filled from the option's own data, so the prompt is the same with AI features on or off. */
export function buildWorkPrompt(threadName: string, option: WorkOptionApi): string {
    const { helper } = option
    const tools = helper.mcp_tools.length > 0 ? ` (tools: ${helper.mcp_tools.join(', ')})` : ''
    return [
        `In PostHog, for the work thread "${threadName}": ${option.label}.`,
        [`What this does: ${helper.does}`, ...helper.fields.map((field) => `${field.label}: ${field.value}`)].join(
            '\n'
        ),
        `Reason: ${option.why}`,
        `Use the PostHog MCP server${tools}. Show me what you will change and wait for my go-ahead before you change anything users see.`,
    ].join('\n\n')
}
