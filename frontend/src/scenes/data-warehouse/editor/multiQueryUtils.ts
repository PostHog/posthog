import type { ASTNode } from '@posthog/hogql-parser'

import { type FormatResult, formatSelect, parseSelect } from './hogqlParserSingleton'

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
 * Pretty-print a full editor document that may contain several `;`-separated
 * statements. Each statement is formatted independently by the WASM formatter
 * and the results are rejoined with `;` separators.
 *
 * All-or-nothing: if any statement isn't a well-formed SELECT, the whole
 * document is left untouched (`ok: false`). This keeps offsets predictable —
 * we never reformat statements 1 and 3 while leaving a broken statement 2 in
 * place, shifting everything around it.
 *
 * The trailing `;` is preserved only if the original input had one; inter-
 * statement separators are always re-emitted. Comments between statements are
 * not preserved (a known limitation of the formatter).
 */
export async function formatQueries(input: string): Promise<FormatResult> {
    const segments = splitQueries(input)
    if (segments.length === 0) {
        return { ok: false, error: 'empty input' }
    }

    const formatted: string[] = []
    for (const segment of segments) {
        const result = await formatSelect(segment.query)
        if (!result.ok) {
            return result
        }
        formatted.push(result.output)
    }

    const endsWithSemicolon = /;\s*$/.test(input)
    const joined = formatted.join(';\n\n')
    return { ok: true, output: endsWithSemicolon ? joined + ';' : joined }
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
 * Recursively collect all SelectQuery/SelectSetQuery nodes from the AST
 * whose position range contains the target offset.
 */
function collectSelectNodesAtOffset(node: unknown, targetOffset: number, results: ASTNode[]): void {
    if (node === null || node === undefined || typeof node !== 'object') {
        return
    }

    if (Array.isArray(node)) {
        for (const item of node) {
            collectSelectNodesAtOffset(item, targetOffset, results)
        }
        return
    }

    const astNode = node as ASTNode
    if (
        (astNode.node === 'SelectQuery' || astNode.node === 'SelectSetQuery') &&
        astNode.start?.offset != null &&
        astNode.end?.offset != null &&
        targetOffset >= astNode.start.offset &&
        targetOffset <= astNode.end.offset
    ) {
        results.push(astNode)
    }

    // Recurse into all object values
    for (const value of Object.values(astNode)) {
        if (typeof value === 'object' && value !== null) {
            collectSelectNodesAtOffset(value, targetOffset, results)
        }
    }
}

/**
 * Find the innermost SELECT subquery at the given cursor offset within a query.
 * Returns null if the cursor is only in the outermost SELECT (no nesting).
 *
 * @param query - The query text to parse (a single top-level query, already split by semicolons)
 * @param cursorOffset - Cursor position in the full editor text
 * @param queryStartOffset - Where this query starts in the full editor text
 */
export async function findInnermostSelectAtOffset(
    query: string,
    cursorOffset: number,
    queryStartOffset: number
): Promise<QueryRange | null> {
    try {
        const ast: ASTNode = JSON.parse(await parseSelect(query))
        if (ast.error || (ast.node !== 'SelectQuery' && ast.node !== 'SelectSetQuery')) {
            return null
        }

        const localOffset = cursorOffset - queryStartOffset
        const results: ASTNode[] = []
        collectSelectNodesAtOffset(ast, localOffset, results)

        // Need at least 2 matches (outer + inner) to have a subquery
        if (results.length < 2) {
            return null
        }

        // Pick the node with the smallest span. JSON key iteration order is not guaranteed
        // to produce children after siblings, so depth-by-order is unreliable — but for any
        // nested pair of SELECTs containing the cursor, the inner one always has a smaller
        // range than any ancestor.
        const innermost = results.reduce((smallest, candidate) => {
            const smallestSpan = smallest.end.offset - smallest.start.offset
            const candidateSpan = candidate.end.offset - candidate.start.offset
            return candidateSpan < smallestSpan ? candidate : smallest
        })
        const text = query.slice(innermost.start.offset, innermost.end.offset)

        return {
            query: text,
            start: queryStartOffset + innermost.start.offset,
            end: queryStartOffset + innermost.end.offset,
        }
    } catch {
        return null
    }
}
