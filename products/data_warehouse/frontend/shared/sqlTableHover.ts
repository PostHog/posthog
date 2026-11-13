import type { Monaco } from '@monaco-editor/react'
import type { CancellationToken, Position, editor, languages } from 'monaco-editor'
import posthog from 'posthog-js'

import type { ASTNode } from '@posthog/hogql-parser'

import { findStatementAtOffset } from 'lib/monaco/multiQueryUtils'
import { characterOffsetToUtf16 } from 'lib/monaco/offsets'
import { parseSelect } from 'scenes/data-warehouse/editor/hogqlParserSingleton'
import { urls } from 'scenes/urls'

import type { DatabaseSchemaTable } from '~/queries/schema/schema-general'

interface TableReference {
    name: string
    start: number
    end: number
}

function tableReferenceInJoin(ast: ASTNode, offset: number, ctes: Set<string>): TableReference | null {
    if (ast.node !== 'JoinExpr' || ast.table?.node !== 'Field') {
        return null
    }
    const field = ast.table
    const name = field.chain.join('.')
    return offset >= field.start.offset && offset < field.end.offset && !ctes.has(name)
        ? { name, start: field.start.offset, end: field.end.offset }
        : null
}

function tableReferenceAtOffset(node: unknown, offset: number, ctes: Set<string>): TableReference | null {
    if (!node || typeof node !== 'object') {
        return null
    }
    const ast = node as ASTNode
    const declaredCtes = ast.ctes ?? ast.initial_select_query?.ctes
    const scope = declaredCtes ? new Set([...ctes, ...declaredCtes.map((cte: ASTNode) => cte.name)]) : ctes
    const reference = tableReferenceInJoin(ast, offset, scope)
    if (reference) {
        return reference
    }
    for (const child of Object.values(ast)) {
        const reference = tableReferenceAtOffset(child, offset, scope)
        if (reference) {
            return reference
        }
    }
    return null
}

export async function findSqlTableReference(query: string, offset: number): Promise<TableReference | null> {
    const statement = findStatementAtOffset(query, offset, { hogql: true })
    if (!statement) {
        return null
    }
    const ast = JSON.parse(await parseSelect(statement.query)) as ASTNode
    if (ast.error) {
        return null
    }
    const characterOffset = Array.from(statement.query.slice(0, offset - statement.start)).length
    const reference = tableReferenceAtOffset(ast, characterOffset, new Set())
    return reference
        ? {
              ...reference,
              start: characterOffsetToUtf16(statement.query, reference.start) + statement.start,
              end: characterOffsetToUtf16(statement.query, reference.end) + statement.start,
          }
        : null
}

function codeBlock(value: string, language = 'plaintext'): string {
    const fence = '`'.repeat(Math.max(3, ...Array.from(value.matchAll(/`+/g), (match) => match[0].length + 1)))
    return `${fence}${language}\n${value}\n${fence}`
}

export function sqlTableHoverContents(table: DatabaseSchemaTable): languages.Hover['contents'] {
    const contents = [{ value: `**${table.type === 'view' ? 'Saved view' : 'Table'}**\n\n${codeBlock(table.name)}` }]
    if (table.description) {
        contents.push({ value: codeBlock(table.description) })
    }
    if (table.type === 'view') {
        const query = table.query.query
        contents.push({ value: codeBlock(query.length > 5000 ? `${query.slice(0, 5000)}\n…` : query, 'sql') })
        const definitionUrl = new URL(urls.sqlEditor({ view_id: table.id }), window.location.origin).href
        contents.push({ value: `[Open view definition](${definitionUrl})` })
    }
    return contents
}

export function registerSqlTableHover(
    monaco: Monaco,
    editorInstance: editor.IStandaloneCodeEditor,
    getTables: () => Record<string, DatabaseSchemaTable>
): void {
    const provider = monaco.languages.registerHoverProvider('hogQL', {
        async provideHover(model: editor.ITextModel, position: Position, token: CancellationToken) {
            if (model !== editorInstance.getModel()) {
                return null
            }
            const version = model.getVersionId()
            try {
                const reference = await findSqlTableReference(model.getValue(), model.getOffsetAt(position))
                if (
                    !reference ||
                    token.isCancellationRequested ||
                    model.isDisposed() ||
                    model.getVersionId() !== version
                ) {
                    return null
                }
                const table = getTables()[reference.name]
                if (!table) {
                    return null
                }
                const start = model.getPositionAt(reference.start)
                const end = model.getPositionAt(reference.end)
                posthog.capture('sql table definition viewed', { table_type: table.type })
                return {
                    range: new monaco.Range(start.lineNumber, start.column, end.lineNumber, end.column),
                    contents: sqlTableHoverContents(table),
                }
            } catch {
                return null
            }
        },
    })
    editorInstance.onDidDispose(() => provider.dispose())
}
