import Papa from 'papaparse'

import { HogQLQuery, HogQLQueryResponse, NodeKind } from '~/queries/schema/schema-general'

function queryCell(value: unknown): string {
    const text = typeof value === 'string' ? value : (JSON.stringify(value) ?? 'null')
    return text.replace(
        /[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]/g,
        (char) => `\\u${char.charCodeAt(0).toString(16).padStart(4, '0')}`
    )
}

export function terminalQueryTable(
    result: Pick<HogQLQueryResponse<unknown[][]>, 'columns' | 'results'>,
    format: 'markdown' | 'csv' | 'tsv'
): string {
    const columns = result.columns ?? result.results[0]?.map((_, index) => `Column ${index + 1}`) ?? []
    const rows: unknown[][] = [columns, ...result.results]
    if (format !== 'markdown') {
        return Papa.unparse(
            rows.map((row) =>
                row.map((value) =>
                    value === null || value === undefined ? '' : typeof value === 'number' ? value : queryCell(value)
                )
            ),
            { delimiter: format === 'csv' ? ',' : '\t', newline: '\n', escapeFormulae: true }
        )
    }
    if (!columns.length) {
        return ''
    }
    const lines = rows.map(
        (row) =>
            `| ${row
                .map((value) =>
                    queryCell(value)
                        .replaceAll('&', '&amp;')
                        .replaceAll('<', '&lt;')
                        .replaceAll('>', '&gt;')
                        .replace(/[\\|`*_[\]~]/g, '\\$&')
                        .replace(/\r\n|\r|\n/g, '<br>')
                )
                .join(' | ')} |`
    )
    lines.splice(1, 0, `| ${columns.map(() => '---').join(' | ')} |`)
    return lines.join('\n')
}

function sqlPaths(value: Record<string, unknown>): string[][] {
    const paths: string[][] = []
    let node = value.query
    const path = ['query']
    while (node && typeof node === 'object' && !Array.isArray(node)) {
        const query = node as Record<string, unknown>
        if (query.kind === 'HogQLQuery' && typeof query.query === 'string') {
            paths.push([...path, 'query'])
            break
        }
        node = query.source
        path.push('source')
    }
    const filters = value.filters as Record<string, unknown> | undefined
    if (filters && typeof filters.hogql === 'string') {
        paths.push(['filters', 'hogql'])
    }
    return paths
}

export function hasTerminalSql(value: unknown): boolean {
    return !!value && typeof value === 'object' && sqlPaths(value as Record<string, unknown>).length > 0
}

export function terminalSql(value: Record<string, unknown>): string {
    const path = sqlPaths(value)[0]
    if (!path) {
        return ''
    }
    let parent = value
    for (const key of path.slice(0, -1)) {
        parent = parent[key] as Record<string, unknown>
    }
    return parent[path[path.length - 1]] as string
}

export function parseTerminalSql(text: string, original: Record<string, unknown>): Record<string, unknown> {
    const metadata: Record<string, unknown> = {}
    for (const path of sqlPaths(original)) {
        metadata[path[0]] ??= structuredClone(original[path[0]])
        let parent = metadata
        for (const key of path.slice(0, -1)) {
            parent = parent[key] as Record<string, unknown>
        }
        parent[path[path.length - 1]] = text
    }
    return metadata
}

export function terminalQuery(text: string, original?: Record<string, unknown>): HogQLQuery {
    let options: Record<string, unknown> = {}
    if (original) {
        let node = original.query
        while (node && typeof node === 'object' && !Array.isArray(node)) {
            const source = node as Record<string, unknown>
            if (source.kind === NodeKind.HogQLQuery) {
                options = source
                break
            }
            node = source.source
        }
    }
    if (!text.trim()) {
        throw new Error('The SQL file is empty. Add a query before running it.')
    }
    return { ...options, kind: NodeKind.HogQLQuery, query: text, tags: { productKey: 'sql_editor', scene: 'Terminal' } }
}
