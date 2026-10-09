export type FilterKey = 'is' | 'createdBy' | 'in' | 'name'

export interface FilterDefinition {
    key: FilterKey
    aliases: string[]
    description: string
    /** Field name the file system search endpoint understands. */
    backendField: 'type' | 'user' | 'path' | 'name'
    /** Whether a value that matches no suggestion is still a valid filter. */
    freeTextValues: boolean
}

export const FILTER_DEFINITIONS: FilterDefinition[] = [
    {
        key: 'is',
        aliases: ['type'],
        description: 'Type, such as dashboard or feature flag',
        backendField: 'type',
        freeTextValues: false,
    },
    {
        key: 'createdBy',
        aliases: ['by', 'author', 'user'],
        description: 'Who created it',
        backendField: 'user',
        freeTextValues: true,
    },
    {
        key: 'in',
        aliases: ['path', 'folder'],
        description: 'Folder it lives in',
        backendField: 'path',
        freeTextValues: true,
    },
    {
        key: 'name',
        aliases: ['title'],
        description: 'Name only, not description',
        backendField: 'name',
        freeTextValues: true,
    },
]

export const MAX_FILTER_KEY_ROWS = 3

export interface ValueOption {
    value: string
    label: string
    /** Extra words a person can type to reach this option, matched by prefix. */
    aliases?: string[]
    /** Icon type for the row, such as a file system type. */
    iconType?: string
}

export interface QueryChip {
    key: FilterKey
    value: string
    label: string
    negated: boolean
}

export interface QueryToken {
    raw: string
    start: number
    end: number
}

export interface ParsedToken {
    negated: boolean
    /** Set only when the token is `key:` with a known key or alias. */
    filter: FilterDefinition | null
    /** Text before the colon, or the whole token without its `-` when there is no colon. */
    keyText: string
    hasColon: boolean
    /** Value after the colon, with surrounding quotes removed. */
    value: string
}

export type CursorContext =
    | { kind: 'empty' }
    | { kind: 'key'; token: QueryToken; partial: string; negated: boolean; matches: FilterDefinition[] }
    | { kind: 'value'; token: QueryToken; filter: FilterDefinition; partial: string; negated: boolean }
    | { kind: 'text'; token: QueryToken | null }

const lower = (value: string): string => value.toLowerCase()

/** Splits on whitespace outside double quotes. An unclosed quote runs to the end of the text. */
export function tokenize(text: string): QueryToken[] {
    const tokens: QueryToken[] = []
    let start = -1
    let inQuote = false
    for (let i = 0; i <= text.length; i++) {
        const char = text[i]
        const atEnd = i === text.length
        if (!atEnd && char === '"') {
            inQuote = !inQuote
        }
        const isBoundary = atEnd || (!inQuote && /\s/.test(char))
        if (isBoundary) {
            if (start !== -1) {
                tokens.push({ raw: text.slice(start, i), start, end: i })
                start = -1
            }
        } else if (start === -1) {
            start = i
        }
    }
    return tokens
}

export function resolveFilterKey(name: string): FilterDefinition | null {
    const needle = lower(name)
    return (
        FILTER_DEFINITIONS.find(
            (definition) => lower(definition.key) === needle || definition.aliases.some((alias) => alias === needle)
        ) ?? null
    )
}

export function unquote(value: string): string {
    let result = value
    if (result.startsWith('"')) {
        result = result.slice(1)
    }
    if (result.endsWith('"')) {
        result = result.slice(0, -1)
    }
    return result
}

export function parseToken(raw: string): ParsedToken {
    const negated = raw.length > 1 && raw.startsWith('-')
    const body = negated ? raw.slice(1) : raw
    const colonIndex = body.indexOf(':')
    if (colonIndex === -1) {
        return { negated, filter: null, keyText: body, hasColon: false, value: '' }
    }
    const keyText = body.slice(0, colonIndex)
    return {
        negated,
        filter: resolveFilterKey(keyText),
        keyText,
        hasColon: true,
        value: unquote(body.slice(colonIndex + 1)),
    }
}

/** Filter definitions whose key or alias starts with the partial text, at most `MAX_FILTER_KEY_ROWS`. */
export function matchFilterKeys(partial: string): FilterDefinition[] {
    const needle = lower(partial)
    if (!needle) {
        return []
    }
    return FILTER_DEFINITIONS.filter(
        (definition) =>
            lower(definition.key).startsWith(needle) || definition.aliases.some((alias) => alias.startsWith(needle))
    ).slice(0, MAX_FILTER_KEY_ROWS)
}

export function tokenAtCursor(text: string, cursor: number): QueryToken | null {
    return tokenize(text).find((token) => token.start <= cursor && cursor <= token.end) ?? null
}

export function getCursorContext(text: string, cursor: number, chips: QueryChip[]): CursorContext {
    if (text.trim() === '' && chips.length === 0) {
        return { kind: 'empty' }
    }
    const token = tokenAtCursor(text, cursor)
    if (!token) {
        return { kind: 'text', token: null }
    }
    const parsed = parseToken(token.raw)
    if (parsed.filter) {
        return { kind: 'value', token, filter: parsed.filter, partial: parsed.value, negated: parsed.negated }
    }
    if (!parsed.hasColon) {
        const matches = matchFilterKeys(parsed.keyText)
        if (matches.length > 0) {
            return { kind: 'key', token, partial: parsed.keyText, negated: parsed.negated, matches }
        }
    }
    return { kind: 'text', token }
}

/** Prefix matches on the label, value, or an alias first, then matches inside a word when allowed. */
export function matchValueOptions(
    options: ValueOption[],
    partial: string,
    { allowSubstring }: { allowSubstring: boolean }
): ValueOption[] {
    const needle = lower(partial)
    if (!needle) {
        return options
    }
    const prefix: ValueOption[] = []
    const substring: ValueOption[] = []
    for (const option of options) {
        const starts = [option.label, option.value, ...(option.aliases ?? [])].map(lower)
        if (starts.some((word) => word.startsWith(needle))) {
            prefix.push(option)
        } else if (allowSubstring && starts.some((word) => word.includes(needle))) {
            substring.push(option)
        }
    }
    return [...prefix, ...substring]
}

/** The exact option a typed value names, if any. */
export function findExactOption(options: ValueOption[], value: string): ValueOption | null {
    const needle = lower(value)
    return (
        options.find(
            (option) =>
                lower(option.value) === needle ||
                lower(option.label) === needle ||
                (option.aliases ?? []).some((alias) => lower(alias) === needle)
        ) ?? null
    )
}

/**
 * The option a fully typed value commits to without a Space: it names the option exactly and no
 * other option starts with it, so typing more could not mean something else.
 */
export function unambiguousOption(options: ValueOption[], value: string): ValueOption | null {
    const exact = findExactOption(options, value)
    if (!exact) {
        return null
    }
    const needle = lower(value)
    const othersStartWith = options.some(
        (option) =>
            option !== exact &&
            [option.label, option.value, ...(option.aliases ?? [])].some((word) => lower(word).startsWith(needle))
    )
    return othersStartWith ? null : exact
}

/** Turns a typed `key:value` into a chip, or returns null when the value is not valid for that key. */
export function resolveChip(
    filter: FilterDefinition,
    value: string,
    negated: boolean,
    options: ValueOption[]
): QueryChip | null {
    const trimmed = value.trim()
    if (!trimmed) {
        return null
    }
    const exact = findExactOption(options, trimmed)
    if (exact) {
        return { key: filter.key, value: exact.value, label: exact.label, negated }
    }
    if (filter.freeTextValues) {
        return { key: filter.key, value: trimmed, label: trimmed, negated }
    }
    return null
}

export function chipId(chip: Pick<QueryChip, 'key' | 'value' | 'negated'>): string {
    return `${chip.negated ? '-' : ''}${chip.key}:${chip.value}`
}

/** Each key holds one chip. A new value for a key replaces the old chip in place. */
export function addChip(chips: QueryChip[], chip: QueryChip): QueryChip[] {
    const index = chips.findIndex((existing) => existing.key === chip.key)
    if (index === -1) {
        return [...chips, chip]
    }
    return chips.map((existing, i) => (i === index ? chip : existing))
}

const quoteIfNeeded = (value: string): string => (/\s/.test(value) ? `"${value}"` : value)

/** The editable text a chip turns back into. */
export function chipToText(chip: QueryChip): string {
    return `${chip.negated ? '-' : ''}${chip.key}:${quoteIfNeeded(chip.value)}`
}

export function filterDefinition(key: FilterKey): FilterDefinition {
    return FILTER_DEFINITIONS.find((definition) => definition.key === key) as FilterDefinition
}

const backendToken = (key: FilterKey, value: string, negated: boolean): string =>
    `${negated ? '-' : ''}${filterDefinition(key).backendField}:${quoteIfNeeded(value)}`

/** Removes a token from the text and returns the new text and where the cursor lands. */
export function removeToken(text: string, token: QueryToken): { text: string; cursor: number } {
    const before = text.slice(0, token.start).replace(/\s+$/, '')
    const after = text.slice(token.end).replace(/^\s+/, '')
    const joined = before && after ? `${before} ${after}` : before || after
    const cursor = before ? before.length + (after ? 1 : 0) : 0
    return { text: joined, cursor }
}

/** Replaces a token with new text and puts the cursor at the end of the replacement. */
export function replaceToken(text: string, token: QueryToken, replacement: string): { text: string; cursor: number } {
    return {
        text: text.slice(0, token.start) + replacement + text.slice(token.end),
        cursor: token.start + replacement.length,
    }
}

/** The values each filter key can suggest. Free-text keys may have none. */
export type FilterOptions = Record<FilterKey, ValueOption[]>

/** Moves every complete, valid filter token in the text into chips. Used for pasted queries. */
export function extractChips(
    text: string,
    chips: QueryChip[],
    options: FilterOptions
): { text: string; chips: QueryChip[] } {
    let nextChips = chips
    const remaining: string[] = []
    for (const token of tokenize(text)) {
        const parsed = parseToken(token.raw)
        const chip = parsed.filter
            ? resolveChip(parsed.filter, parsed.value, parsed.negated, options[parsed.filter.key])
            : null
        if (chip) {
            nextChips = addChip(nextChips, chip)
        } else {
            remaining.push(token.raw)
        }
    }
    return { text: remaining.join(' '), chips: nextChips }
}

export interface ResolvedQuery {
    /** The filters in effect: the chips, with a valid `key:value` still in the text standing in for that key's chip. */
    filters: QueryChip[]
    /** The text that is not a filter token. */
    freeText: string
    /** The `search` string for the file system endpoint. */
    backendSearch: string
}

/**
 * Resolves the input once per change, so every consumer agrees on what applies. A typed value
 * previews what committing it would do, so `createdBy:Ca` narrows results before it is committed.
 * Filters come first in `backendSearch`, sorted, so the same query typed in another order hits the
 * same cache entry.
 */
export function resolveQuery(text: string, chips: QueryChip[], options: FilterOptions): ResolvedQuery {
    const filters = new Map<FilterKey, QueryChip>(chips.map((chip) => [chip.key, chip]))
    const freeTokens: string[] = []
    for (const token of tokenize(text)) {
        const parsed = parseToken(token.raw)
        if (!parsed.filter) {
            freeTokens.push(token.raw)
            continue
        }
        const chip = resolveChip(parsed.filter, parsed.value, parsed.negated, options[parsed.filter.key])
        if (chip) {
            filters.set(chip.key, chip)
        }
    }
    const filterTokens = [...filters.values()].map((chip) => backendToken(chip.key, chip.value, chip.negated)).sort()
    return {
        filters: [...filters.values()],
        freeText: freeTokens.join(' '),
        backendSearch: [...filterTokens, ...freeTokens].join(' '),
    }
}

/** The raw query as a person would type it, chips included. Used for "Ask PostHog AI". */
export function queryAsText(text: string, chips: QueryChip[]): string {
    return [...chips.map(chipToText), text.trim()].filter(Boolean).join(' ')
}

export interface InputEdit {
    previousText: string
    previousCursor: number
    text: string
    cursor: number
}

const typedSpaceAt = (edit: InputEdit): boolean =>
    edit.cursor === edit.previousCursor + 1 &&
    edit.text[edit.previousCursor] === ' ' &&
    edit.text.slice(0, edit.previousCursor) + edit.text.slice(edit.cursor) === edit.previousText

/**
 * A space typed at the start or after another space separates nothing. It mostly follows a value
 * that already committed on its last letter, so it is dropped rather than left as stray text.
 */
export function isRedundantSpace(edit: InputEdit): boolean {
    return typedSpaceAt(edit) && (edit.previousCursor === 0 || /\s/.test(edit.previousText[edit.previousCursor - 1]))
}

/**
 * The chip an edit commits, as if its suggestion were picked: a space typed right after a valid
 * `key:value`, or a value that names exactly one option. Returns the token to remove from `text`.
 */
export function chipCommittedByEdit(
    edit: InputEdit,
    chips: QueryChip[],
    options: FilterOptions
): { chip: QueryChip; token: QueryToken; via: 'space' | 'typed' } | null {
    const { previousText, previousCursor, text, cursor } = edit
    const typedSpace = typedSpaceAt(edit)
    const context = typedSpace
        ? getCursorContext(previousText, previousCursor, chips)
        : getCursorContext(text, cursor, chips)
    const end = typedSpace ? previousCursor : cursor
    if (context.kind !== 'value' || context.token.end !== end) {
        return null
    }
    // A value inside an open quote is still being typed, whether the edit is a space or a letter.
    const rawValue = context.token.raw.slice(context.token.raw.indexOf(':') + 1)
    if (rawValue.startsWith('"') && (rawValue.length === 1 || !rawValue.endsWith('"'))) {
        return null
    }
    if (!typedSpace) {
        const option = unambiguousOption(options[context.filter.key], context.partial)
        return option
            ? {
                  chip: { key: context.filter.key, value: option.value, label: option.label, negated: context.negated },
                  token: context.token,
                  via: 'typed',
              }
            : null
    }
    const chip = resolveChip(context.filter, context.partial, context.negated, options[context.filter.key])
    return chip ? { chip, token: context.token, via: 'space' } : null
}
