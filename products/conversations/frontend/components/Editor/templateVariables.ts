import { JSONContent } from '@tiptap/core'

/** Variables a quick action can reference with {{name}} tokens, resolved from the current ticket. */
export const TEMPLATE_VARIABLES = [
    { token: 'customer.name', description: "The customer's name" },
    { token: 'ticket.number', description: 'The ticket number' },
    { token: 'agent.name', description: 'Your full name' },
    { token: 'agent.first_name', description: 'Your first name' },
] as const

export type TemplateVariableToken = (typeof TEMPLATE_VARIABLES)[number]['token']

export type TemplateVariableValues = Partial<Record<TemplateVariableToken, string>>

// Matches {{ token }} with optional surrounding whitespace.
const VARIABLE_PATTERN = /\{\{\s*([\w.]+)\s*\}\}/g

/**
 * Replace {{variable}} tokens in a string with their resolved values.
 * Unknown or unset tokens resolve to an empty string so no raw {{...}} leaks to the customer.
 */
export function applyTemplateVariables(text: string, values: TemplateVariableValues): string {
    return text.replace(VARIABLE_PATTERN, (_match, token: string) => {
        const value = values[token as TemplateVariableToken]
        return value ?? ''
    })
}

/** Apply variable substitution to every text node of a TipTap document, returning a new tree. */
export function applyTemplateVariablesToRichContent(content: JSONContent, values: TemplateVariableValues): JSONContent {
    const next: JSONContent = { ...content }
    if (typeof next.text === 'string') {
        next.text = applyTemplateVariables(next.text, values)
    }
    if (Array.isArray(next.content)) {
        next.content = next.content.map((child) => applyTemplateVariablesToRichContent(child, values))
    }
    return next
}
