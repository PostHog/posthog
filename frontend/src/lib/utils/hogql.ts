import { dayjs } from 'lib/dayjs'
import { getAppContext } from 'lib/utils/getAppContext'

export function isQuoted(identifier: string): boolean {
    return (
        (identifier.startsWith('"') && identifier.endsWith('"')) ||
        (identifier.startsWith('`') && identifier.endsWith('`'))
    )
}

// Mirrors escape_chars_map in posthog/hogql/escape_sql.py: backslash and control chars must be escaped so a quoted identifier round-trips losslessly through the HogQL parser.
const HOGQL_IDENTIFIER_ESCAPE_MAP: Record<string, string> = {
    '\b': '\\b',
    '\f': '\\f',
    '\r': '\\r',
    '\n': '\\n',
    '\t': '\\t',
    '\0': '\\0',
    '\x07': '\\a',
    '\v': '\\v',
    '\\': '\\\\',
}

/** Make sure the property key is wrapped in quotes if it contains any special characters. */
export function escapePropertyAsHogQLIdentifier(identifier: string): string {
    if (identifier.match(/^[A-Za-z_$][A-Za-z0-9_$]*$/)) {
        // Same regex as in the backend escape_hogql_identifier
        return identifier // This identifier is simple
    }
    if (isQuoted(identifier)) {
        return identifier // This identifier is already quoted
    }
    return escapeRawPropertyAsHogQLIdentifier(identifier)
}

export function escapeRawPropertyAsHogQLIdentifier(identifier: string): string {
    if (identifier.match(/^[A-Za-z_$][A-Za-z0-9_$]*$/)) {
        return identifier
    }
    // Escape backslashes and control chars, then wrap; double an inner backtick (the parser rejects a backslash-escaped delimiter). The double-quote path needs no quote escaping since it is only taken when the identifier has no `"`.
    const escaped = Array.from(identifier, (c) => HOGQL_IDENTIFIER_ESCAPE_MAP[c] || c).join('')
    return !identifier.includes('"') ? `"${escaped}"` : `\`${escaped.replaceAll('`', '``')}\``
}

/** Quote each segment of a dotted HogQL reference independently. */
export function escapeDottedHogQLIdentifier(identifier: string): string {
    if (isQuoted(identifier) || !identifier.includes('.')) {
        return escapePropertyAsHogQLIdentifier(identifier)
    }

    return identifier
        .split('.')
        .map((segment) => escapePropertyAsHogQLIdentifier(segment))
        .join('.')
}

declare const __hogqlBrand: unique symbol
export type HogQLQueryString = string & { readonly [__hogqlBrand]: void }

export interface HogQLIdentifier {
    __hogql_identifier: true
    identifier: string
}

function hogQLIdentifier(identifier: string): HogQLIdentifier {
    return {
        __hogql_identifier: true,
        identifier,
    }
}

function isHogQLIdentifier(value: any): value is HogQLIdentifier {
    return !!value?.__hogql_identifier
}

export interface HogQLRaw {
    __hogql_raw: true
    raw: string
}

function hogQLRaw(raw: string): HogQLRaw {
    return {
        __hogql_raw: true,
        raw,
    }
}

function isHogQLRaw(value: any): value is HogQLRaw {
    return !!value?.__hogql_raw
}

const ESCAPE_CHARS_MAP: Record<string, string> = {
    '\b': '\\b',
    '\f': '\\f',
    '\r': '\\r',
    '\n': '\\n',
    '\t': '\\t',
    '\0': '\\0',
    '\x07': '\\a',
    '\v': '\\v',
    '\\': '\\\\',
    "'": "\\'",
}

export function escapeHogQLString(value: string): string {
    let escaped = ''
    for (const char of value) {
        escaped += ESCAPE_CHARS_MAP[char] ?? char
    }
    return `'${escaped}'`
}

function formatHogQLValue(value: any): string {
    if (Array.isArray(value)) {
        return `[${value.map(formatHogQLValue).join(', ')}]`
    } else if (dayjs.isDayjs(value)) {
        const timezone = getAppContext()?.current_team?.timezone || 'UTC'
        return value.tz(timezone).format("'YYYY-MM-DD HH:mm:ss'")
    } else if (isHogQLIdentifier(value)) {
        return escapePropertyAsHogQLIdentifier(value.identifier)
    } else if (isHogQLRaw(value)) {
        return value.raw
    } else if (typeof value === 'string') {
        return escapeHogQLString(value)
    } else if (typeof value === 'number') {
        return String(value)
    } else if (value === null) {
        throw new Error(
            `null cannot be interpolated for SQL. if a null check is needed, make 'IS NULL' part of your query`
        )
    } else {
        throw new Error(`Unsupported interpolated value type: ${typeof value}`)
    }
}

/**
 * Template tag for HogQL formatting. Handles formatting of values for you.
 * @example hogql`SELECT * FROM events WHERE properties.text = ${text} AND timestamp > ${dayjs()}`
 */
export function hogql(strings: TemplateStringsArray, ...values: any[]): HogQLQueryString {
    return strings.reduce(
        (acc, str, i) => acc + str + (i < strings.length - 1 ? formatHogQLValue(values[i]) : ''),
        ''
    ) as unknown as HogQLQueryString
}
hogql.identifier = hogQLIdentifier
hogql.raw = hogQLRaw
