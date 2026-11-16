import {
    type AstRange,
    type SelectComparison,
    compareParsedSelects,
    innermostSelectRangeFromAst,
    tablesAndColumnsFromAst,
} from './hogqlAst'
import { parseSelect } from './hogqlParserSingleton'
import { askParserWorker, isParserWorkerUnavailable } from './hogqlParserWorkerClient'

// Runs the HogQL parse in a worker so a long query does not freeze the editor. Falls back to
// parsing on the main thread whenever the worker is unavailable — no Worker (jsdom), the bundle
// isn't served, init times out, or a request fails. The fallback is slow but correct, and it runs
// the same walkers as the worker, so behavior does not change with it.

/** Parse on the main thread. Blocks, so it is only for when the worker cannot be used. */
async function parseOnMainThread(query: string): Promise<any | null> {
    try {
        return JSON.parse(await parseSelect(query))
    } catch {
        return null
    }
}

export async function analyzeInnermostSelect(query: string, localOffset: number): Promise<AstRange | null> {
    if (!isParserWorkerUnavailable()) {
        try {
            return await askParserWorker({ op: 'innermostSelect', query, localOffset })
        } catch {
            // fall through to the main thread
        }
    }
    const ast = await parseOnMainThread(query)
    return ast ? innermostSelectRangeFromAst(ast, localOffset) : null
}

export async function analyzeTablesAndColumns(query: string): Promise<Record<string, Record<string, boolean>>> {
    if (!isParserWorkerUnavailable()) {
        try {
            return await askParserWorker({ op: 'tablesAndColumns', query })
        } catch {
            // fall through to the main thread
        }
    }
    const ast = await parseOnMainThread(query)
    return ast ? tablesAndColumnsFromAst(ast) : {}
}

const SELECT_COMPARISONS: ReadonlySet<unknown> = new Set<SelectComparison>(['same', 'different', 'unparsable'])

export async function compareSelectQueries(query: string, other: string): Promise<SelectComparison> {
    if (!isParserWorkerUnavailable()) {
        try {
            const result = await askParserWorker({ op: 'compareSelects', query, other })
            if (SELECT_COMPARISONS.has(result)) {
                return result
            }
        } catch {}
    }
    return compareParsedSelects(await parseSelect(query, true), await parseSelect(other, true))
}
