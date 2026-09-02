import { analyzeTablesAndColumns } from './hogqlParserWorkerManager'

export { normalizeIdentifier } from './hogqlAst'

// Scans the query for a `{<name>` placeholder, skipping strings and comments so a literal like
// '{filters}' does not count. `name` is matched when followed by `}`, `.`, or `(`, which covers
// the plain, field, and column-bound placeholder forms the backend rejects in views.
const queryUsesPlaceholder = (query: string | null, name: string): boolean => {
    if (!query) {
        return false
    }

    // Built once because `name` is fixed for the whole scan. Inlining these as template literals in
    // the loop allocates three strings for every scanned character.
    const plain = `{${name}}`
    const field = `{${name}.`
    const columnBound = `{${name}(`

    let i = 0
    while (i < query.length) {
        const ch = query[i]

        if (ch === "'" || ch === '"' || ch === '`') {
            const quote = ch
            i++
            while (i < query.length) {
                if (query[i] === '\\') {
                    i += 2
                    continue
                }
                if (query[i] === quote && query[i + 1] === quote) {
                    i += 2
                    continue
                }
                if (query[i] === quote) {
                    i++
                    break
                }
                i++
            }
            continue
        }

        // Single-line comments the HogQL lexer skips: SQL `--`, C-style `//`, and MySQL-style `#`.
        // A `#` right before a digit is a positional reference (`#1`), not a comment.
        if ((ch === '-' && query[i + 1] === '-') || (ch === '/' && query[i + 1] === '/')) {
            i += 2
            while (i < query.length && query[i] !== '\n' && query[i] !== '\r') {
                i++
            }
            continue
        }

        if (ch === '#' && !/[0-9]/.test(query[i + 1] ?? '')) {
            i++
            while (i < query.length && query[i] !== '\n' && query[i] !== '\r') {
                i++
            }
            continue
        }

        if (ch === '/' && query[i + 1] === '*') {
            i += 2
            while (i < query.length) {
                if (query[i] === '*' && query[i + 1] === '/') {
                    i += 2
                    break
                }
                i++
            }
            continue
        }

        if (query.startsWith(plain, i) || query.startsWith(field, i) || query.startsWith(columnBound, i)) {
            return true
        }

        i++
    }

    return false
}

export const queryUsesFiltersPlaceholder = (query: string | null): boolean => queryUsesPlaceholder(query, 'filters')

export const queryUsesVariablesPlaceholder = (query: string | null): boolean => queryUsesPlaceholder(query, 'variables')

export const parseQueryTablesAndColumns = async (
    queryInput: string | null
): Promise<Record<string, Record<string, boolean>>> => {
    if (!queryInput) {
        return {}
    }
    return await analyzeTablesAndColumns(queryInput)
}
