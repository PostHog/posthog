import { analyzeTablesAndColumns } from './hogqlParserWorkerManager'

export { normalizeIdentifier } from './hogqlAst'

const FILTERS_BOUND_PREFIX = '{filters('

// Returns the index after the string literal or comment starting at `i`, or null when neither starts there.
const skipNonCode = (query: string, i: number): number | null => {
    const ch = query[i]

    if (ch === "'" || ch === '"' || ch === '`') {
        const quote = ch
        let j = i + 1
        while (j < query.length) {
            if (query[j] === '\\') {
                j += 2
                continue
            }
            if (query[j] === quote && query[j + 1] === quote) {
                j += 2
                continue
            }
            if (query[j] === quote) {
                return j + 1
            }
            j++
        }
        return j
    }

    if (ch === '-' && query[i + 1] === '-') {
        let j = i + 2
        while (j < query.length && query[j] !== '\n') {
            j++
        }
        return j
    }

    if (ch === '/' && query[i + 1] === '*') {
        let j = i + 2
        while (j < query.length) {
            if (query[j] === '*' && query[j + 1] === '/') {
                return j + 2
            }
            j++
        }
        return j
    }

    return null
}

export const queryUsesFiltersPlaceholder = (query: string | null): boolean => {
    if (!query) {
        return false
    }

    let i = 0
    while (i < query.length) {
        const skipped = skipNonCode(query, i)
        if (skipped !== null) {
            i = skipped
            continue
        }

        if (
            query.startsWith('{filters}', i) ||
            query.startsWith('{filters.', i) ||
            query.startsWith(FILTERS_BOUND_PREFIX, i)
        ) {
            return true
        }

        i++
    }

    return false
}

const readBindingArgs = (query: string, start: number): { args: string[]; end: number } => {
    const args: string[] = []
    let current = ''
    let depth = 0
    let i = start

    while (i < query.length) {
        const skipped = skipNonCode(query, i)
        if (skipped !== null) {
            current += query.slice(i, skipped)
            i = skipped
            continue
        }

        const ch = query[i]
        if (ch === ')' && depth === 0) {
            args.push(current)
            return { args, end: i + 1 }
        }
        if (ch === ',' && depth === 0) {
            args.push(current)
            current = ''
            i++
            continue
        }
        if (ch === '(') {
            depth++
        } else if (ch === ')') {
            depth--
        }
        current += ch
        i++
    }

    args.push(current)
    return { args, end: i }
}

const BINDING_KEY_REGEX = /\bas\s+(?:`([^`]+)`|"([^"]+)"|'([^']+)'|([A-Za-z_]\w*))\s*$/i

const bindingKey = (arg: string): string | null => {
    const match = BINDING_KEY_REGEX.exec(arg.trim())
    if (!match) {
        return null
    }
    return match[1] ?? match[2] ?? match[3] ?? match[4]
}

/**
 * Keys bound by the column-bound `{filters(expr AS key, ...)}` placeholder, or null when the query
 * uses no such placeholder. Keys keep their case, because the query runner matches them literally.
 */
export const filtersPlaceholderBindings = (query: string | null): string[] | null => {
    if (!query) {
        return null
    }

    let keys: string[] | null = null
    let i = 0
    while (i < query.length) {
        const skipped = skipNonCode(query, i)
        if (skipped !== null) {
            i = skipped
            continue
        }

        if (query.startsWith(FILTERS_BOUND_PREFIX, i)) {
            const { args, end } = readBindingArgs(query, i + FILTERS_BOUND_PREFIX.length)
            keys = keys ?? []
            for (const arg of args) {
                const key = bindingKey(arg)
                if (key !== null) {
                    keys.push(key)
                }
            }
            i = end
            continue
        }

        i++
    }

    return keys
}

export const parseQueryTablesAndColumns = async (
    queryInput: string | null
): Promise<Record<string, Record<string, boolean>>> => {
    if (!queryInput) {
        return {}
    }
    return await analyzeTablesAndColumns(queryInput)
}
