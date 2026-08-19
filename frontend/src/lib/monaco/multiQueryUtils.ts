export interface QueryRange {
    /** The SQL text of this individual statement */
    query: string
    /** 0-based character offset where the statement starts in the full input */
    start: number
    /** 0-based character offset where the statement ends in the full input */
    end: number
}

/**
 * Split a multi-statement SQL input into individual queries by splitting on
 * semicolons that are outside of string literals, comments, and parenthesized
 * blocks (subqueries, CTEs, function calls).
 */
export function splitQueries(input: string): QueryRange[] {
    if (!input.trim()) {
        return []
    }

    const ranges: QueryRange[] = []
    let segmentStart = 0
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
            const segment = input.slice(segmentStart, i)
            const trimmed = segment.trim()
            if (trimmed) {
                const trimStart = segmentStart + segment.indexOf(trimmed)
                ranges.push({ query: trimmed, start: trimStart, end: trimStart + trimmed.length })
            }
            segmentStart = i + 1
        }

        i++
    }

    // Remaining text after last semicolon
    const segment = input.slice(segmentStart)
    const trailing = segment.trim()
    if (trailing) {
        const trimStart = segmentStart + segment.indexOf(trailing)
        ranges.push({ query: trailing, start: trimStart, end: trimStart + trailing.length })
    }

    return ranges
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

/**
 * Find the query that fully contains the given character range, without the
 * nearest-preceding fallback of `findQueryAtCursor`. Returns null when the range
 * straddles a statement boundary or sits in the whitespace between statements.
 */
export function findQueryContainingRange(
    queries: QueryRange[],
    startOffset: number,
    endOffset: number
): QueryRange | null {
    return queries.find((q) => startOffset >= q.start && endOffset <= q.end) ?? null
}
