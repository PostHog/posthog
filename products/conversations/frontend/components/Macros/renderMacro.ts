import type { UserType } from '~/types'

import type { Ticket } from '../../types'

export interface MacroContext {
    customer: {
        first_name: string | null
        name: string | null
        email: string | null
    }
    agent: {
        first_name: string | null
        name: string | null
    }
    ticket: {
        number: string | null
    }
}

const VARIABLE_PATTERN = /\{\{\s*([a-z0-9_.]+)\s*\}\}/gi
// serializeToMarkdown escapes `{`, `}`, `.`, and `_`, so a typed variable would be stored as
// \{\{customer\.first\_name\}\} and never match.
const ESCAPED_MACRO_TOKEN = /\\\{\\\{\s*((?:[a-z0-9]|\\[._])+)\s*\\\}\\\}/gi
const MARKDOWN_ESCAPED_CHAR = /\\([\\`*_{}[\]()#+\-.!|])/g

export function unescapeMacroTokens(body: string): string {
    ESCAPED_MACRO_TOKEN.lastIndex = 0
    return body.replace(ESCAPED_MACRO_TOKEN, (_match, key: string) => `{{${key.replace(/\\([._])/g, '$1')}}}`)
}

function lookup(key: string, ctx: MacroContext): string | null {
    switch (key) {
        case 'customer.first_name':
            return ctx.customer.first_name
        case 'customer.name':
            return ctx.customer.name
        case 'customer.email':
            return ctx.customer.email
        case 'agent.first_name':
            return ctx.agent.first_name
        case 'agent.name':
            return ctx.agent.name
        case 'ticket.number':
            return ctx.ticket.number
        default:
            return null
    }
}

/** Leaves a variable in place when it has no value, so the agent sees the gap before sending. */
export function renderMacro(body: string, ctx: MacroContext): string {
    return unescapeMacroTokens(body).replace(VARIABLE_PATTERN, (token, key: string) => {
        const value = lookup(key.toLowerCase(), ctx)?.trim()
        return value ? value : token
    })
}

export function macroPreview(body: string): string {
    const line = unescapeMacroTokens(body)
        .replace(MARKDOWN_ESCAPED_CHAR, '$1')
        .split('\n')
        .map((part) => part.trim())
        .find(Boolean)
    if (!line) {
        return ''
    }
    return line.length > 80 ? `${line.slice(0, 79)}…` : line
}

export function isStartOfMacroSlash(charBefore: string): boolean {
    return charBefore === '' || /\s/.test(charBefore)
}

function trimmedString(value: unknown): string | null {
    return typeof value === 'string' && value.trim() ? value.trim() : null
}

export function macroContextFromTicket(ticket: Ticket | null, user: UserType | null): MacroContext {
    const named = trimmedString(ticket?.person?.properties?.name) || trimmedString(ticket?.anonymous_traits?.name)
    const email =
        trimmedString(ticket?.person?.properties?.email) ||
        trimmedString(ticket?.anonymous_traits?.email) ||
        trimmedString(ticket?.email_from)
    const agentFirst = trimmedString(user?.first_name)
    const agentLast = trimmedString(user?.last_name)
    const agentName = [agentFirst, agentLast].filter(Boolean).join(' ') || trimmedString(user?.email)
    return {
        customer: {
            first_name: named ? (named.split(/\s+/)[0] ?? null) : null,
            name: named || email,
            email,
        },
        agent: { first_name: agentFirst, name: agentName },
        ticket: { number: ticket ? String(ticket.ticket_number) : null },
    }
}
