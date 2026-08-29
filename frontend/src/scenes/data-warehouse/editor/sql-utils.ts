import { analyzeTablesAndColumns } from './hogqlParserWorkerManager'

export { normalizeIdentifier } from './hogqlAst'

// Scans the query for a `{<name>` placeholder, skipping strings and comments so a literal like
// '{filters}' does not count. `name` is matched when followed by `}`, `.`, or `(`, which covers
// the plain, field, and column-bound placeholder forms the backend rejects in views.
const queryUsesPlaceholder = (query: string | null, name: string): boolean => {
    if (!query) {
        return false
    }

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

        if (ch === '-' && query[i + 1] === '-') {
            i += 2
            while (i < query.length && query[i] !== '\n') {
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

        if (query.startsWith(`{${name}}`, i) || query.startsWith(`{${name}.`, i) || query.startsWith(`{${name}(`, i)) {
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
