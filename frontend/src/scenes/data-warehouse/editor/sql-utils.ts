import { analyzeTablesAndColumns } from './hogqlParserWorkerManager'

export { normalizeIdentifier } from './hogqlAst'

export const queryUsesFiltersPlaceholder = (query: string | null): boolean => {
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

        if (query.startsWith('{filters}', i) || query.startsWith('{filters.', i) || query.startsWith('{filters(', i)) {
            return true
        }

        i++
    }

    return false
}

// Returns the widest cell length in a column, including the header. Uses a reduce so a large
// result set does not spread one argument per row into Math.max, which throws RangeError.
export const columnMaxContentLength = (rows: any[][], columnIndex: number, headerLength: number): number => {
    return rows.reduce((max: number, row: any[]) => {
        const content = row[columnIndex]
        const length =
            typeof content === 'string'
                ? content.length
                : content === null || content === undefined
                  ? 0
                  : content.toString().length
        return length > max ? length : max
    }, headerLength)
}

export const parseQueryTablesAndColumns = async (
    queryInput: string | null
): Promise<Record<string, Record<string, boolean>>> => {
    if (!queryInput) {
        return {}
    }
    return await analyzeTablesAndColumns(queryInput)
}
