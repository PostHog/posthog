import { JSONContent } from '@tiptap/core'

/** Variables a macro can reference with {{name}} tokens, resolved from the current ticket. */
export const MACRO_VARIABLES = [
    { token: 'customer.name', description: "The customer's name" },
    { token: 'ticket.number', description: 'The ticket number' },
    { token: 'agent.name', description: 'Your full name' },
    { token: 'agent.first_name', description: 'Your first name' },
] as const

export type MacroVariableToken = (typeof MACRO_VARIABLES)[number]['token']

export type MacroVariableValues = Partial<Record<MacroVariableToken, string>>

// Matches {{ token }} with optional surrounding whitespace.
const VARIABLE_PATTERN = /\{\{\s*([\w.]+)\s*\}\}/g

/**
 * Replace {{variable}} tokens in a string with their resolved values.
 * Unknown or unset tokens resolve to an empty string so no raw {{...}} leaks to the customer.
 */
export function applyMacroVariables(text: string, values: MacroVariableValues): string {
    return text.replace(VARIABLE_PATTERN, (_match, token: string) => {
        const value = values[token as MacroVariableToken]
        return value ?? ''
    })
}

/** Apply variable substitution to every text node of a TipTap document, returning a new tree. */
export function applyMacroVariablesToRichContent(content: JSONContent, values: MacroVariableValues): JSONContent {
    const next: JSONContent = { ...content }
    if (typeof next.text === 'string') {
        next.text = applyMacroVariables(next.text, values)
    }
    if (Array.isArray(next.content)) {
        next.content = next.content.map((child) => applyMacroVariablesToRichContent(child, values))
    }
    return next
}
