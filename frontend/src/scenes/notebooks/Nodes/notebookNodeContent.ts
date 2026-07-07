import { parseMarkdownNotebook } from 'lib/components/MarkdownNotebook/markdown'
import { JSONContent } from 'lib/components/RichContentEditor/types'

import { NOTEBOOK_NODE_TYPE_TO_MARKDOWN_TAG } from '../Notebook/markdownNotebookV2'
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

export type HogqlSqlNodeSummary = {
    nodeId: string
    code: string
    returnVariable: string
    hogqlSqlIndex: number
    title: string
}

export type SqlV2NodeSummary = {
    nodeId: string
    code: string
    returnVariable: string
    tablesUsed: string[]
    sqlV2Index: number
    title: string
}

export type NotebookDependencyUsage = {
    nodeId: string
    nodeType: NotebookNodeType
    nodeIndex: number
    title: string
}

export type NotebookDependencyNode = {
    nodeId: string
    nodeType: NotebookNodeType
    nodeIndex: number
    title: string
    exports: string[]
    uses: string[]
    code?: string
    returnVariable?: string
}

export type NotebookDependencyGraph = {
    nodes: NotebookDependencyNode[]
    nodesById: Record<string, NotebookDependencyNode>
    upstreamSourcesByNode: Record<string, Record<string, NotebookDependencyUsage>>
    downstreamUsageByNode: Record<string, Record<string, NotebookDependencyUsage[]>>
}

// TODO: The SQL parsing logic in this file is very rough. This is on purpose.
// The HogQL WASM parser is coming. Once we have that, we'll revisit this part and make it robust.

const stripSqlComments = (sql: string): string => {
    return sql.replace(/--.*$/gm, '').replace(/\/\*[\s\S]*?\*\//g, '')
}

export const extractHogqlPlaceholders = (sql: string): string[] => {
    const cleanedSql = stripSqlComments(sql || '')
    const placeholders: string[] = []
    const placeholderPattern = /\{([A-Za-z_][\w$]*)\}/g
    const excludedPlaceholderNames = new Set([
        'filters', // Reserved for auto-injected global date/property filters in HogQL notebook queries.
    ])
    let match = placeholderPattern.exec(cleanedSql)
    while (match) {
        const name = match[1]
        if (name && !excludedPlaceholderNames.has(name) && !placeholders.includes(name)) {
            placeholders.push(name)
        }
        match = placeholderPattern.exec(cleanedSql)
    }
    return placeholders
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
        const remainingSql = cleanedSql.slice(match.index + match[0].length)
        if (remainingSql.trimStart().startsWith('(')) {
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

export const resolveDuckSqlReturnVariable = (returnVariable: string): string => {
    return returnVariable.trim() || 'duck_df'
}

const buildUniqueDuckSqlReturnVariable = (baseReturnVariable: string, used: Set<string>): string => {
    const normalizedBase = normalizeDuckSqlIdentifier(baseReturnVariable)
    if (!used.has(normalizedBase)) {
        return baseReturnVariable
    }

    let suffix = 2
    while (true) {
        const candidate = `${baseReturnVariable}_${suffix}`
        if (!used.has(normalizeDuckSqlIdentifier(candidate))) {
            return candidate
        }
        suffix += 1
    }
}

export const getUniqueDuckSqlReturnVariable = (
    nodes: DuckSqlNodeSummary[],
    nodeId: string,
    fallbackReturnVariable: string
): string => {
    const used = new Set<string>()
    let resolvedReturnVariable = resolveDuckSqlReturnVariable(fallbackReturnVariable)
    let resolvedFromNodes = false

    nodes.forEach((node) => {
        const baseReturnVariable = resolveDuckSqlReturnVariable(node.returnVariable)
        const uniqueReturnVariable = buildUniqueDuckSqlReturnVariable(baseReturnVariable, used)
        used.add(normalizeDuckSqlIdentifier(uniqueReturnVariable))

        if (node.nodeId === nodeId) {
            resolvedReturnVariable = uniqueReturnVariable
            resolvedFromNodes = true
        }
    })

    if (!resolvedFromNodes) {
        resolvedReturnVariable = buildUniqueDuckSqlReturnVariable(resolvedReturnVariable, used)
    }

    return resolvedReturnVariable
}

export const resolveHogqlReturnVariable = (returnVariable: string): string => {
    return returnVariable.trim() || 'hogql_df'
}

const buildUniqueHogqlReturnVariable = (baseReturnVariable: string, used: Set<string>): string => {
    const normalizedBase = normalizeSqlIdentifier(baseReturnVariable)
    if (!used.has(normalizedBase)) {
        return baseReturnVariable
    }

    let suffix = 2
    while (true) {
        const candidate = `${baseReturnVariable}_${suffix}`
        if (!used.has(normalizeSqlIdentifier(candidate))) {
            return candidate
        }
        suffix += 1
    }
}

export const getUniqueHogqlReturnVariable = (
    nodes: HogqlSqlNodeSummary[],
    nodeId: string,
    fallbackReturnVariable: string
): string => {
    const used = new Set<string>()
    let resolvedReturnVariable = resolveHogqlReturnVariable(fallbackReturnVariable)
    let resolvedFromNodes = false

    nodes.forEach((node) => {
        const baseReturnVariable = resolveHogqlReturnVariable(node.returnVariable)
        const uniqueReturnVariable = buildUniqueHogqlReturnVariable(baseReturnVariable, used)
        used.add(normalizeSqlIdentifier(uniqueReturnVariable))

        if (node.nodeId === nodeId) {
            resolvedReturnVariable = uniqueReturnVariable
            resolvedFromNodes = true
        }
    })

    if (!resolvedFromNodes) {
        resolvedReturnVariable = buildUniqueHogqlReturnVariable(resolvedReturnVariable, used)
    }

    return resolvedReturnVariable
}

// SQLV2 nodes reference upstream nodes by bare table name (like DuckSQL) but use HogQL
// identifiers (like the HogQL node), so they reuse both extraction helpers.
export const resolveSqlV2ReturnVariable = (returnVariable: string): string => {
    return returnVariable.trim() || 'sql_df'
}

const buildUniqueSqlV2ReturnVariable = (baseReturnVariable: string, used: Set<string>): string => {
    const normalizedBase = normalizeSqlIdentifier(baseReturnVariable)
    if (!used.has(normalizedBase)) {
        return baseReturnVariable
    }

    let suffix = 2
    while (true) {
        const candidate = `${baseReturnVariable}_${suffix}`
        if (!used.has(normalizeSqlIdentifier(candidate))) {
            return candidate
        }
        suffix += 1
    }
}

export const getUniqueSqlV2ReturnVariable = (
    nodes: SqlV2NodeSummary[],
    nodeId: string,
    fallbackReturnVariable: string
): string => {
    const used = new Set<string>()
    let resolvedReturnVariable = resolveSqlV2ReturnVariable(fallbackReturnVariable)
    let resolvedFromNodes = false

    nodes.forEach((node) => {
        const baseReturnVariable = resolveSqlV2ReturnVariable(node.returnVariable)
        const uniqueReturnVariable = buildUniqueSqlV2ReturnVariable(baseReturnVariable, used)
        used.add(normalizeSqlIdentifier(uniqueReturnVariable))

        if (node.nodeId === nodeId) {
            resolvedReturnVariable = uniqueReturnVariable
            resolvedFromNodes = true
        }
    })

    if (!resolvedFromNodes) {
        resolvedReturnVariable = buildUniqueSqlV2ReturnVariable(resolvedReturnVariable, used)
    }

    return resolvedReturnVariable
}

// Markdown notebooks hold their cells as component tags inside a single markdown attribute,
// so walking the tiptap JSON alone never finds them. Expand the given cell tag into
// tiptap-shaped nodes so the collectors and the dependency graph see the same cells in both
// notebook formats. Scoped to the revamped-notebook cell types (SQLV2 + kernel Python):
// expanding the other node types would change their (markdown-blind) summaries and naming.
const expandMarkdownNotebookNodesOfType = (node: any, nodeType: NotebookNodeType): JSONContent[] => {
    if (typeof node?.attrs?.markdown !== 'string') {
        return []
    }
    return parseMarkdownNotebook(node.attrs.markdown).nodes.flatMap((block) =>
        block.type === 'component' && block.tagName === NOTEBOOK_NODE_TYPE_TO_MARKDOWN_TAG[nodeType]
            ? [
                  {
                      type: nodeType,
                      attrs: {
                          ...block.props,
                          // Prefer the persisted nodeId prop: the parsed block id is a content
                          // fingerprint, which drifts from the live cell id as soon as any prop
                          // changes (running a cell writes runId/result into its props).
                          nodeId:
                              typeof block.props.nodeId === 'string' && block.props.nodeId
                                  ? block.props.nodeId
                                  : block.id,
                      },
                  },
              ]
            : []
    )
}

const expandMarkdownNotebookSqlV2Nodes = (node: any): JSONContent[] =>
    expandMarkdownNotebookNodesOfType(node, NotebookNodeType.SQLV2)

export const collectSqlV2Nodes = (content?: JSONContent | null): SqlV2NodeSummary[] => {
    if (!content || typeof content !== 'object') {
        return []
    }

    const nodes: SqlV2NodeSummary[] = []
    const usedReturnVariables = new Set<string>()

    const walk = (node: any): void => {
        if (!node || typeof node !== 'object') {
            return
        }
        if (node.type === NotebookNodeType.SQLV2) {
            const attrs = node.attrs ?? {}
            const code = typeof attrs.code === 'string' ? attrs.code : ''
            const baseReturnVariable = resolveSqlV2ReturnVariable(
                typeof attrs.returnVariable === 'string' ? attrs.returnVariable : 'sql_df'
            )
            const returnVariable = buildUniqueSqlV2ReturnVariable(baseReturnVariable, usedReturnVariables)
            usedReturnVariables.add(normalizeSqlIdentifier(returnVariable))
            nodes.push({
                nodeId: attrs.nodeId ?? '',
                code,
                returnVariable,
                tablesUsed: extractDuckSqlTables(code),
                sqlV2Index: nodes.length + 1,
                title: typeof attrs.title === 'string' ? attrs.title : '',
            })
        }
        if (node.type === NotebookNodeType.MarkdownNotebook) {
            expandMarkdownNotebookSqlV2Nodes(node).forEach(walk)
        }
        if (Array.isArray(node.content)) {
            node.content.forEach(walk)
        }
    }

    walk(content)
    return nodes
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

export type PythonKernelNodeSummary = {
    nodeId: string
    returnVariable: string
}

// Kernel-run Python cells (revamped notebooks): each binds its result to `returnVariable` in
// the kernel namespace. Unlike the SQL collectors the names are NOT disambiguated — they are
// exactly the kernel variables, so a duplicated returnVariable means last-run-wins, matching
// kernel semantics. Markdown-aware (unlike the legacy collectPythonNodes) because revamped
// markdown notebooks store their cells as `<Python …/>` component tags.
export const collectPythonKernelNodes = (content?: JSONContent | null): PythonKernelNodeSummary[] => {
    if (!content || typeof content !== 'object') {
        return []
    }

    const nodes: PythonKernelNodeSummary[] = []

    const walk = (node: any): void => {
        if (!node || typeof node !== 'object') {
            return
        }
        if (node.type === NotebookNodeType.Python) {
            const attrs = node.attrs ?? {}
            const returnVariable =
                typeof attrs.returnVariable === 'string' && attrs.returnVariable.trim()
                    ? attrs.returnVariable.trim()
                    : 'df'
            nodes.push({ nodeId: attrs.nodeId ?? '', returnVariable })
        }
        if (node.type === NotebookNodeType.MarkdownNotebook) {
            expandMarkdownNotebookNodesOfType(node, NotebookNodeType.Python).forEach(walk)
        }
        if (Array.isArray(node.content)) {
            node.content.forEach(walk)
        }
    }

    walk(content)
    return nodes
}

export const collectHogqlSqlNodes = (content?: JSONContent | null): HogqlSqlNodeSummary[] => {
    if (!content || typeof content !== 'object') {
        return []
    }

    const nodes: HogqlSqlNodeSummary[] = []
    const usedReturnVariables = new Set<string>()

    const walk = (node: any): void => {
        if (!node || typeof node !== 'object') {
            return
        }
        if (node.type === NotebookNodeType.HogQLSQL) {
            const attrs = node.attrs ?? {}
            const code = typeof attrs.code === 'string' ? attrs.code : ''
            const baseReturnVariable = resolveHogqlReturnVariable(
                typeof attrs.returnVariable === 'string' ? attrs.returnVariable : 'hogql_df'
            )
            const returnVariable = buildUniqueHogqlReturnVariable(baseReturnVariable, usedReturnVariables)
            usedReturnVariables.add(normalizeSqlIdentifier(returnVariable))
            nodes.push({
                nodeId: attrs.nodeId ?? '',
                code,
                returnVariable,
                hogqlSqlIndex: nodes.length + 1,
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
    const usedReturnVariables = new Set<string>()

    const walk = (node: any): void => {
        if (!node || typeof node !== 'object') {
            return
        }
        if (node.type === NotebookNodeType.DuckSQL) {
            const attrs = node.attrs ?? {}
            const code = typeof attrs.code === 'string' ? attrs.code : ''
            const baseReturnVariable = resolveDuckSqlReturnVariable(
                typeof attrs.returnVariable === 'string' ? attrs.returnVariable : 'duck_df'
            )
            const returnVariable = buildUniqueDuckSqlReturnVariable(baseReturnVariable, usedReturnVariables)
            usedReturnVariables.add(normalizeDuckSqlIdentifier(returnVariable))
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

const buildDependencyUsage = (node: NotebookDependencyNode): NotebookDependencyUsage => {
    return {
        nodeId: node.nodeId,
        nodeType: node.nodeType,
        nodeIndex: node.nodeIndex,
        title: node.title,
    }
}

const matchesUsage = (exportName: string, usageName: string, usageNodeType: NotebookNodeType): boolean => {
    if (usageNodeType === NotebookNodeType.DuckSQL) {
        return normalizeDuckSqlIdentifier(exportName) === normalizeDuckSqlIdentifier(usageName)
    }
    return exportName === usageName
}

export const buildNotebookDependencyGraph = (content?: JSONContent | null): NotebookDependencyGraph => {
    if (!content || typeof content !== 'object') {
        return {
            nodes: [],
            nodesById: {},
            upstreamSourcesByNode: {},
            downstreamUsageByNode: {},
        }
    }

    const nodes: NotebookDependencyNode[] = []
    let pythonIndex = 0
    let duckSqlIndex = 0
    let hogqlSqlIndex = 0
    let sqlV2Index = 0
    const usedDuckSqlReturnVariables = new Set<string>()
    const usedHogqlReturnVariables = new Set<string>()
    const usedSqlV2ReturnVariables = new Set<string>()

    const walk = (node: any): void => {
        if (!node || typeof node !== 'object') {
            return
        }

        if (node.type === NotebookNodeType.Python) {
            const attrs = node.attrs ?? {}
            pythonIndex += 1
            const exportedGlobals = Array.isArray(attrs.globalsExportedWithTypes)
                ? attrs.globalsExportedWithTypes.map((entry: any) => entry?.name).filter(Boolean)
                : []
            nodes.push({
                nodeId: attrs.nodeId ?? '',
                nodeType: NotebookNodeType.Python,
                nodeIndex: pythonIndex,
                title: typeof attrs.title === 'string' ? attrs.title : '',
                exports: exportedGlobals,
                uses: Array.isArray(attrs.globalsUsed) ? attrs.globalsUsed : [],
                code: typeof attrs.code === 'string' ? attrs.code : '',
            })
        }

        if (node.type === NotebookNodeType.DuckSQL) {
            const attrs = node.attrs ?? {}
            duckSqlIndex += 1
            const baseReturnVariable = resolveDuckSqlReturnVariable(
                typeof attrs.returnVariable === 'string' ? attrs.returnVariable : 'duck_df'
            )
            const returnVariable = buildUniqueDuckSqlReturnVariable(baseReturnVariable, usedDuckSqlReturnVariables)
            usedDuckSqlReturnVariables.add(normalizeDuckSqlIdentifier(returnVariable))
            const code = typeof attrs.code === 'string' ? attrs.code : ''
            nodes.push({
                nodeId: attrs.nodeId ?? '',
                nodeType: NotebookNodeType.DuckSQL,
                nodeIndex: duckSqlIndex,
                title: typeof attrs.title === 'string' ? attrs.title : '',
                exports: returnVariable ? [returnVariable] : [],
                uses: extractDuckSqlTables(code),
                code,
                returnVariable,
            })
        }

        if (node.type === NotebookNodeType.HogQLSQL) {
            const attrs = node.attrs ?? {}
            hogqlSqlIndex += 1
            const baseReturnVariable = resolveHogqlReturnVariable(
                typeof attrs.returnVariable === 'string' ? attrs.returnVariable : 'hogql_df'
            )
            const returnVariable = buildUniqueHogqlReturnVariable(baseReturnVariable, usedHogqlReturnVariables)
            usedHogqlReturnVariables.add(normalizeSqlIdentifier(returnVariable))
            const code = typeof attrs.code === 'string' ? attrs.code : ''
            nodes.push({
                nodeId: attrs.nodeId ?? '',
                nodeType: NotebookNodeType.HogQLSQL,
                nodeIndex: hogqlSqlIndex,
                title: typeof attrs.title === 'string' ? attrs.title : '',
                exports: returnVariable ? [returnVariable] : [],
                uses: extractHogqlPlaceholders(code),
                code,
                returnVariable,
            })
        }

        if (node.type === NotebookNodeType.SQLV2) {
            const attrs = node.attrs ?? {}
            sqlV2Index += 1
            const baseReturnVariable = resolveSqlV2ReturnVariable(
                typeof attrs.returnVariable === 'string' ? attrs.returnVariable : 'sql_df'
            )
            const returnVariable = buildUniqueSqlV2ReturnVariable(baseReturnVariable, usedSqlV2ReturnVariables)
            usedSqlV2ReturnVariables.add(normalizeSqlIdentifier(returnVariable))
            const code = typeof attrs.code === 'string' ? attrs.code : ''
            nodes.push({
                nodeId: attrs.nodeId ?? '',
                nodeType: NotebookNodeType.SQLV2,
                nodeIndex: sqlV2Index,
                title: typeof attrs.title === 'string' ? attrs.title : '',
                exports: returnVariable ? [returnVariable] : [],
                uses: extractDuckSqlTables(code),
                code,
                returnVariable,
            })
        }

        if (node.type === NotebookNodeType.MarkdownNotebook) {
            expandMarkdownNotebookSqlV2Nodes(node).forEach(walk)
        }

        if (Array.isArray(node.content)) {
            node.content.forEach(walk)
        }
    }

    walk(content)

    const nodesById = nodes.reduce<Record<string, NotebookDependencyNode>>((acc, node) => {
        if (node.nodeId) {
            acc[node.nodeId] = node
        }
        return acc
    }, {})

    const upstreamSourcesByNode: Record<string, Record<string, NotebookDependencyUsage>> = {}
    const downstreamUsageByNode: Record<string, Record<string, NotebookDependencyUsage[]>> = {}

    nodes.forEach((node, nodeIndex) => {
        const upstreamNodes = nodes.slice(0, nodeIndex)
        const downstreamNodes = nodes.slice(nodeIndex + 1)

        const upstreamSources = node.uses.reduce<Record<string, NotebookDependencyUsage>>((acc, usageName) => {
            const source = upstreamNodes.find((upstreamNode) =>
                upstreamNode.exports.some((exportName) => matchesUsage(exportName, usageName, node.nodeType))
            )
            if (source) {
                acc[usageName] = buildDependencyUsage(source)
            }
            return acc
        }, {})

        const downstreamUsage = node.exports.reduce<Record<string, NotebookDependencyUsage[]>>((acc, exportName) => {
            acc[exportName] = downstreamNodes
                .filter((downstreamNode) =>
                    downstreamNode.uses.some((usageName) =>
                        matchesUsage(exportName, usageName, downstreamNode.nodeType)
                    )
                )
                .map(buildDependencyUsage)
            return acc
        }, {})

        upstreamSourcesByNode[node.nodeId] = upstreamSources
        downstreamUsageByNode[node.nodeId] = downstreamUsage
    })

    return {
        nodes,
        nodesById,
        upstreamSourcesByNode,
        downstreamUsageByNode,
    }
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
