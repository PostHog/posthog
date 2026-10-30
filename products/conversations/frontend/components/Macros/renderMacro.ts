import { markdownToHtml } from 'lib/utils/markdown'

import type { UserType } from '~/types'

import type { TicketMacroApi } from '../../generated/api.schemas'
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
// Private-use characters: markdown leaves them alone in text, and the body is cleared of them first.
const VALUE_SLOT = /\uE000(\d+)\uE001/g
// marked percent-encodes the slot when it sits in a link or image URL.
const ENCODED_VALUE_SLOT = /%EE%80%80(\d+)%EE%80%81/gi
const SLOT_CHARS = /[\uE000\uE001]/g
const HTML_ENTITIES: Record<string, string> = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }

function escapeHtml(value: string): string {
    return value.replace(/[&<>"']/g, (char) => HTML_ENTITIES[char])
}

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

/**
 * Returns HTML for the composer. Leaves a variable in place when it has no value, so the agent sees the gap
 * before sending. Values are customer data, so they go in after the markdown is parsed and stay literal text.
 */
export function renderMacro(body: string, ctx: MacroContext): string {
    const values: string[] = []
    const markdown = unescapeMacroTokens(body.replace(SLOT_CHARS, '')).replace(
        VARIABLE_PATTERN,
        (token, key: string) => {
            const value = lookup(key.toLowerCase(), ctx)?.trim()
            if (!value) {
                return token
            }
            values.push(value)
            return `\uE000${values.length - 1}\uE001`
        }
    )
    const fill =
        (encode: (value: string) => string) =>
        (slot: string, index: string): string => {
            const value = values[Number(index)]
            return value === undefined ? slot : escapeHtml(encode(value))
        }
    // In a URL the value is a single component, so a customer value cannot change the link's scheme or host.
    return markdownToHtml(markdown)
        .replace(ENCODED_VALUE_SLOT, fill(encodeURIComponent))
        .replace(
            VALUE_SLOT,
            fill((value) => value)
        )
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

function matchRank(macro: TicketMacroApi, needle: string): number | null {
    const shortcut = macro.shortcut ?? ''
    if (shortcut === needle) {
        return 0
    }
    if (shortcut.startsWith(needle)) {
        return 1
    }
    if (macro.name.toLowerCase().includes(needle)) {
        return 2
    }
    if (shortcut.includes(needle)) {
        return 3
    }
    return null
}

/** Exact shortcut first, so `/refund` never loses to a more used `/refund-partial`. Keeps input order within a tier. */
export function matchMacros(macros: TicketMacroApi[], query: string, limit = 8): TicketMacroApi[] {
    const needle = query.trim().toLowerCase()
    if (!needle) {
        return macros.slice(0, limit)
    }
    return macros
        .map((macro) => ({ macro, rank: matchRank(macro, needle) }))
        .filter((entry): entry is { macro: TicketMacroApi; rank: number } => entry.rank !== null)
        .sort((a, b) => a.rank - b.rank)
        .slice(0, limit)
        .map((entry) => entry.macro)
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
