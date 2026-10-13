import { type QueryRange } from 'lib/monaco/multiQueryUtils'

import { analyzeInnermostSelect } from './hogqlParserWorkerManager'

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
        const range = await analyzeInnermostSelect(query, cursorOffset - queryStartOffset)
        if (!range) {
            return null
        }

        return {
            query: query.slice(range.start, range.end),
            start: queryStartOffset + range.start,
            end: queryStartOffset + range.end,
        }
    } catch {
        return null
    }
}
