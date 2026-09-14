export interface QueryRange {
    /** The SQL text of this individual statement */
    query: string
    /** 0-based character offset where the statement starts in the full input */
    start: number
    /** 0-based character offset where the statement ends in the full input */
    end: number
}

/**
 * Offsets of the semicolons that separate top-level statements, skipping those inside string
 * literals, comments, and parenthesized blocks (subqueries, CTEs, function calls).
 */
function findSeparatorOffsets(input: string): number[] {
    const separators: number[] = []
    let i = 0
    let parenDepth = 0

    while (i < input.length) {
        const ch = input[i]

        // Skip over quoted strings. Supports both backslash escapes and SQL-style
        // doubled delimiters ('', "", ``) inside the string. If the literal is
        // unterminated, we rewind past the opening delimiter so a stray quote
        // doesn't silently mask every subsequent semicolon.
        if (ch === "'" || ch === '"' || ch === '`') {
            const quote = ch
            const openPos = i
            let closed = false
            i++
            while (i < input.length) {
                if (input[i] === '\\') {
                    i += 2 // skip escaped character
                    continue
                }
                if (input[i] === quote && input[i + 1] === quote) {
                    i += 2 // doubled delimiter — stays inside the literal
                    continue
                }
                if (input[i] === quote) {
                    i++ // closing quote
                    closed = true
                    break
                }
                i++
            }
            if (!closed) {
                i = openPos + 1 // treat unterminated opener as a regular character
            }
            continue
        }

        // Skip single-line comments
        if (ch === '-' && input[i + 1] === '-') {
            i += 2
            while (i < input.length && input[i] !== '\n') {
                i++
            }
            continue
        }

        // Skip block comments; unterminated /* … rewinds the same way as quotes.
        if (ch === '/' && input[i + 1] === '*') {
            const openPos = i
            let closed = false
            i += 2
            while (i < input.length) {
                if (input[i] === '*' && input[i + 1] === '/') {
                    i += 2 // skip closing */
                    closed = true
                    break
                }
                i++
            }
            if (!closed) {
                i = openPos + 1
            }
            continue
        }

        // Track parenthesis depth — semicolons inside parens are not separators
        if (ch === '(') {
            parenDepth++
            i++
            continue
        }
        if (ch === ')') {
            parenDepth = Math.max(0, parenDepth - 1)
            i++
            continue
        }

        if (ch === ';' && parenDepth === 0) {
            separators.push(i)
        }

        i++
    }

    return separators
}

/**
 * Split a multi-statement SQL input into individual queries, one per top-level semicolon.
 * Each range covers the trimmed statement text, so the whitespace around a statement sits
 * outside it. Segments holding no statement text are dropped.
 */
export function splitQueries(input: string): QueryRange[] {
    if (!input.trim()) {
        return []
    }

    const ranges: QueryRange[] = []
    for (const { start, end } of statementSegments(input)) {
        const segment = input.slice(start, end)
        const trimmed = segment.trim()
        if (trimmed) {
            const trimStart = start + segment.indexOf(trimmed)
            ranges.push({ query: trimmed, start: trimStart, end: trimStart + trimmed.length })
        }
    }

    return ranges
}

/**
 * The half-open text spans between the top-level semicolons, including the whitespace around
 * each statement. A cursor at `end` sits on the separator itself, which still belongs to the
 * statement before it.
 */
function statementSegments(input: string): { start: number; end: number }[] {
    const segments: { start: number; end: number }[] = []
    let start = 0
    for (const separator of findSeparatorOffsets(input)) {
        segments.push({ start, end: separator })
        start = separator + 1
    }
    segments.push({ start, end: input.length })

    return segments
}

/**
 * Find the statement the cursor is editing, as the raw text between the semicolons surrounding it.
 * The whitespace around a statement belongs to it, so a cursor resting after a trailing space still
 * resolves to the statement it follows. Offsets are not trimmed, which keeps a position measured
 * against the full input valid once `start` is subtracted from it.
 *
 * Returns null when the cursor sits in a segment that holds no statement text yet, such as directly
 * after a semicolon.
 */
export function findStatementAtOffset(input: string, cursorOffset: number): QueryRange | null {
    const segment = statementSegments(input).find(({ start, end }) => cursorOffset >= start && cursorOffset <= end)
    if (!segment || !input.slice(segment.start, segment.end).trim()) {
        return null
    }

    return { query: input.slice(segment.start, segment.end), start: segment.start, end: segment.end }
}

/**
 * Find the query whose range contains the given cursor offset.
 * If the cursor is between queries (e.g. on a semicolon or whitespace),
 * returns the nearest preceding query. Returns null for empty input.
 */
export function findQueryAtCursor(queries: QueryRange[], cursorOffset: number): QueryRange | null {
    if (queries.length === 0) {
        return null
    }

    // Direct hit — cursor is inside a query range
    for (const q of queries) {
        if (cursorOffset >= q.start && cursorOffset <= q.end) {
            return q
        }
    }

    // Cursor is between queries or after the last one — pick the nearest preceding query
    let best: QueryRange | null = null
    for (const q of queries) {
        if (q.end <= cursorOffset) {
            best = q
        }
    }

    return best ?? queries[0]
}
