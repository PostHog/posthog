import { escapePropertyAsHogQLIdentifier } from '~/queries/utils'

import { analyzeTablesAndColumns } from './hogqlParserWorkerManager'

export { normalizeIdentifier } from './hogqlAst'

export interface SidebarColumnInsert {
    /** Text to write into the editor. */
    text: string
    /** Replace the whole query rather than inserting at the cursor. */
    replaceWholeQuery: boolean
    /** Cursor column to leave after a scaffold, so the next column click extends the SELECT list. */
    cursorColumn?: number
}

/**
 * Decide what a column click in the schema sidebar writes into the SQL editor.
 *
 * A blank editor gets a runnable `SELECT <column> FROM <table>` scaffold. Without it a single
 * click drops a bare identifier that runs as its own query and fails with "Unknown table". Later
 * clicks add a comma before the column so two identifiers do not fuse into one (e.g. "idcreated_at").
 */
export function buildSidebarColumnInsert({
    columnText,
    tableName,
    fullText,
    charBeforeCursor,
}: {
    columnText: string
    tableName: string | null
    fullText: string
    charBeforeCursor: string
}): SidebarColumnInsert {
    if (tableName && fullText.trim() === '') {
        const select = `SELECT ${columnText}`
        return {
            text: `${select}\nFROM ${escapePropertyAsHogQLIdentifier(tableName)}`,
            replaceWholeQuery: true,
            cursorColumn: select.length + 1,
        }
    }
    const needsSeparator = /[\w`".]/.test(charBeforeCursor)
    return { text: needsSeparator ? `, ${columnText}` : columnText, replaceWholeQuery: false }
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
