import { JSONContent } from 'lib/components/RichContentEditor/types'

import { NotebookNodeType } from '../types'

export type PythonNodeSummary = {
    nodeId: string
    code: string
    globalsUsed: string[]
    pythonIndex: number
    title: string
}

export type DuckSqlNodeSummary = {
    nodeId: string
    code: string
    returnVariable: string
    tablesUsed: string[]
    duckSqlIndex: number
    title: string
}

export type VariableUsage = {
    nodeId: string
    pythonIndex: number
    title: string
}

export type DuckSqlUsage = {
    nodeId: string
    duckSqlIndex: number
    title: string
}

const stripSqlComments = (sql: string): string => {
    return sql.replace(/--.*$/gm, '').replace(/\/\*[\s\S]*?\*\//g, '')
}

const extractCteNames = (sql: string): Set<string> => {
    const cteNames = new Set<string>()
    const ctePattern = /(?:with|,)\s*([A-Za-z_][\w$]*)\s+as\s*\(/gi
    let match = ctePattern.exec(sql)
    while (match) {
        cteNames.add(match[1].toLowerCase())
        match = ctePattern.exec(sql)
    }
    return cteNames
}

const normalizeSqlIdentifier = (identifier: string): string => {
    return identifier
        .trim()
        .replace(/["'`[\]]/g, '')
        .toLowerCase()
}

export const extractDuckSqlTables = (sql: string): string[] => {
    const cleanedSql = stripSqlComments(sql || '')
    const cteNames = extractCteNames(cleanedSql)
    const tableNames = new Map<string, string>()
    const tablePattern = /\b(from|join)\s+([^\s,;()]+)/gi
    let match = tablePattern.exec(cleanedSql)
    while (match) {
        const rawTable = match[2]
        if (rawTable.startsWith('(')) {
            match = tablePattern.exec(cleanedSql)
            continue
        }
        const normalized = normalizeSqlIdentifier(rawTable)
        if (!normalized || normalized === 'select' || cteNames.has(normalized)) {
            match = tablePattern.exec(cleanedSql)
            continue
        }
        if (!tableNames.has(normalized)) {
            tableNames.set(normalized, rawTable.replace(/["'`[\]]/g, ''))
        }
        match = tablePattern.exec(cleanedSql)
    }
    return Array.from(tableNames.values())
}

export const normalizeDuckSqlIdentifier = (identifier: string): string => {
    return normalizeSqlIdentifier(identifier)
}

export const collectPythonNodes = (content?: JSONContent | null): PythonNodeSummary[] => {
    if (!content || typeof content !== 'object') {
        return []
    }

    const nodes: PythonNodeSummary[] = []

    const walk = (node: any): void => {
        if (!node || typeof node !== 'object') {
            return
        }
        if (node.type === NotebookNodeType.Python) {
            const attrs = node.attrs ?? {}
            nodes.push({
                nodeId: attrs.nodeId ?? '',
                code: typeof attrs.code === 'string' ? attrs.code : '',
                globalsUsed: Array.isArray(attrs.globalsUsed) ? attrs.globalsUsed : [],
                pythonIndex: nodes.length + 1,
                title: typeof attrs.title === 'string' ? attrs.title : '',
            })
        }
        if (Array.isArray(node.content)) {
            node.content.forEach(walk)
        }
    }

    walk(content)
    return nodes
}

export const collectDuckSqlNodes = (content?: JSONContent | null): DuckSqlNodeSummary[] => {
    if (!content || typeof content !== 'object') {
        return []
    }

    const nodes: DuckSqlNodeSummary[] = []

    const walk = (node: any): void => {
        if (!node || typeof node !== 'object') {
            return
        }
        if (node.type === NotebookNodeType.DuckSQL) {
            const attrs = node.attrs ?? {}
            const code = typeof attrs.code === 'string' ? attrs.code : ''
            const returnVariable = typeof attrs.returnVariable === 'string' ? attrs.returnVariable : 'duck_df'
            nodes.push({
                nodeId: attrs.nodeId ?? '',
                code,
                returnVariable,
                tablesUsed: extractDuckSqlTables(code),
                duckSqlIndex: nodes.length + 1,
                title: typeof attrs.title === 'string' ? attrs.title : '',
            })
        }
        if (Array.isArray(node.content)) {
            node.content.forEach(walk)
        }
    }

    walk(content)
    return nodes
}

export const collectNodeIndices = (
    content: Record<string, any> | null | undefined,
    predicate: (node: Record<string, any>) => boolean
): Map<string, number> => {
    if (!content || typeof content !== 'object') {
        return new Map()
    }

    const nodeIndices = new Map<string, number>()
    let currentIndex = 0

    const walk = (node: Record<string, any> | null | undefined): void => {
        if (!node || typeof node !== 'object') {
            return
        }

        if (predicate(node)) {
            const nodeId = node.attrs?.nodeId
            if (nodeId) {
                currentIndex += 1
                nodeIndices.set(nodeId, currentIndex)
            }
        }

        if (Array.isArray(node.content)) {
            node.content.forEach(walk)
        }
    }

    walk(content)
    return nodeIndices
}
