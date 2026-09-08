import type { ASTNode } from '@posthog/hogql-parser'

import { type AstRange, innermostSelectRangeFromAst, tablesAndColumnsFromAst } from './hogqlAst'

// Parsing HogQL is a synchronous WASM call over the whole query — roughly 36ms per 1000
// characters, so seconds on a long one. On the main thread that freezes the editor after every
// edit, so it happens here instead.

export type HogqlParserQuestion =
    | { op: 'innermostSelect'; query: string; localOffset: number }
    | { op: 'tablesAndColumns'; query: string }

export type HogqlParserRequest = HogqlParserQuestion & { id: number }

export type HogqlParserResponse =
    | { type: 'ready' }
    | { id: number; result: AstRange | null | Record<string, Record<string, boolean>> }
    | { id: number; error: string }

let parserPromise: Promise<{ parseSelect: (input: string, isInternal?: boolean) => string }> | null = null

function getParser(): Promise<{ parseSelect: (input: string, isInternal?: boolean) => string }> {
    if (!parserPromise) {
        parserPromise = import('@posthog/hogql-parser')
            .then((mod) => mod.default())
            .catch((error) => {
                parserPromise = null // let the next request retry initialization
                throw error
            })
    }
    return parserPromise as Promise<{ parseSelect: (input: string, isInternal?: boolean) => string }>
}

// The two ops are driven by different debounces over the same text, and a cursor move re-asks for
// a range without changing the text at all. Holding the last AST here means those cost a walk
// instead of a parse — and the AST (megabytes of JSON) never has to reach the main thread.
let lastQuery: string | null = null
let lastAst: ASTNode | null = null

async function astFor(query: string): Promise<ASTNode | null> {
    if (lastQuery === query) {
        return lastAst
    }
    const parser = await getParser()
    let ast: ASTNode | null
    try {
        ast = JSON.parse(parser.parseSelect(query, false)) as ASTNode
    } catch {
        // Invalid SQL is expected while typing — cache the miss so we don't reparse it either.
        ast = null
    }
    lastQuery = query
    lastAst = ast
    return ast
}

self.onmessage = async (event: MessageEvent<HogqlParserRequest>): Promise<void> => {
    const request = event.data
    try {
        const ast = await astFor(request.query)
        if (!ast) {
            self.postMessage({
                id: request.id,
                result: request.op === 'innermostSelect' ? null : {},
            } satisfies HogqlParserResponse)
            return
        }
        const result =
            request.op === 'innermostSelect'
                ? innermostSelectRangeFromAst(ast, request.localOffset)
                : tablesAndColumnsFromAst(ast)
        self.postMessage({ id: request.id, result } satisfies HogqlParserResponse)
    } catch (error) {
        self.postMessage({
            id: request.id,
            error: error instanceof Error ? error.message : 'Unknown parser worker error',
        } satisfies HogqlParserResponse)
    }
}

self.postMessage({ type: 'ready' } satisfies HogqlParserResponse)
