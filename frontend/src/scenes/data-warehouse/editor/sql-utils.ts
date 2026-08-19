import { escapePropertyAsHogQLIdentifier } from '~/queries/utils'

import { analyzeTablesAndColumns } from './hogqlParserWorkerManager'

export { normalizeIdentifier } from './hogqlAst'

export interface SidebarColumnInsert {
    /** Text to write into the editor. */
    text: string
    /** Replace the whole query rather than inserting at the cursor. */
    replaceWholeQuery: boolean
    /** Offset within `text` where the cursor should land after the edit. */
    cursorOffsetInText: number
}

// Clause keywords that must not be comma-separated from an adjacent column. A comma before `FROM`
// is invalid SQL, so when one of these sits next to the cursor we separate with a space instead.
const SQL_CLAUSE_KEYWORDS = new Set([
    'select',
    'from',
    'where',
    'group',
    'by',
    'having',
    'order',
    'limit',
    'offset',
    'join',
    'left',
    'right',
    'inner',
    'outer',
    'full',
    'cross',
    'on',
    'using',
    'union',
    'intersect',
    'except',
    'and',
    'or',
    'as',
    'asc',
    'desc',
    'over',
    'window',
])

const leadingSeparator = (before: string): string => {
    const trimmed = before.replace(/\s+$/, '')
    if (trimmed === '') {
        return ''
    }
    const lastChar = trimmed[trimmed.length - 1]
    if (lastChar === ',' || lastChar === '(') {
        return ''
    }
    // A trailing "." is a half-typed qualified reference such as "events." — the click completes it
    // ("events.id"), so it takes no separator. A comma here would produce invalid "events., id".
    if (lastChar === '.') {
        return ''
    }
    const word = trimmed.match(/[`"\w.]+$/)?.[0] ?? ''
    const hadSpace = before.length > trimmed.length
    if (word && SQL_CLAUSE_KEYWORDS.has(word.toLowerCase())) {
        return hadSpace ? '' : ' '
    }
    if (word || lastChar === ')') {
        return ', '
    }
    return hadSpace ? '' : ' '
}

const trailingSeparator = (after: string): string => {
    const trimmed = after.replace(/^\s+/, '')
    if (trimmed === '') {
        return ''
    }
    const firstChar = trimmed[0]
    if (firstChar === ',' || firstChar === ')') {
        return ''
    }
    const word = trimmed.match(/^[`"\w.]+/)?.[0] ?? ''
    const hadSpace = after.length > trimmed.length
    if (word && SQL_CLAUSE_KEYWORDS.has(word.toLowerCase())) {
        return hadSpace ? '' : ' '
    }
    if (word) {
        return ', '
    }
    return hadSpace ? '' : ' '
}

/**
 * Decide what a column click in the schema sidebar writes into the SQL editor.
 *
 * A blank editor gets a runnable `SELECT <column> FROM <table>` scaffold. Without it a single
 * click drops a bare identifier that runs as its own query and fails with "Unknown table".
 *
 * An insert into an existing query separates the column from the text on both sides of the cursor,
 * so two identifiers never fuse into one (e.g. "idcreated_at"). Adjacent columns get a comma;
 * an adjacent clause keyword such as FROM gets a space, since a comma before it is invalid SQL.
 */
export function buildSidebarColumnInsert({
    columnText,
    tableName,
    fullText,
    cursorOffset,
}: {
    columnText: string
    tableName: string | null
    fullText: string
    cursorOffset: number
}): SidebarColumnInsert {
    if (tableName && fullText.trim() === '') {
        const prefix = 'SELECT '
        return {
            text: `${prefix}${columnText}\nFROM ${escapePropertyAsHogQLIdentifier(tableName)}`,
            replaceWholeQuery: true,
            cursorOffsetInText: prefix.length + columnText.length,
        }
    }
    const before = leadingSeparator(fullText.slice(0, cursorOffset))
    const after = trailingSeparator(fullText.slice(cursorOffset))
    return {
        text: `${before}${columnText}${after}`,
        replaceWholeQuery: false,
        cursorOffsetInText: before.length + columnText.length,
    }
}

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

export const parseQueryTablesAndColumns = async (
    queryInput: string | null
): Promise<Record<string, Record<string, boolean>>> => {
    if (!queryInput) {
        return {}
    }
    return await analyzeTablesAndColumns(queryInput)
}
