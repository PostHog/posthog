import { parseMarkdownNotebook } from 'lib/components/MarkdownNotebook/markdown'
import { JSONContent } from 'lib/components/RichContentEditor/types'

import { NOTEBOOK_NODE_TYPE_TO_MARKDOWN_TAG, getSqlV2PropsFromQueryProp } from '../Notebook/markdownNotebookV2'
import { NotebookNodeType } from '../types'

function isInsightDataframeNode(node: JSONContent): boolean {
    return (
        node.type === NotebookNodeType.Query &&
        !!(
            node.attrs?.id ||
            node.attrs?.query?.kind === 'InsightVizNode' ||
            node.attrs?.query?.kind === 'SavedInsightNode' ||
            node.attrs?.dataframeQuery
        )
    )
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
    // SQLV2 only: the data source the cell runs against, so a chain-dispatched run targets the
    // same one its own Run button would.
    connectionId?: string | null
    sendRawQuery?: boolean
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

// Rough by design, like the SQL extraction above: identifiers a Python cell's code mentions,
// with string literals, comments, and attribute tails stripped. Only ever intersected with
// sibling exports (matchesUsage), so a false positive just marks an extra cell stale.
export const extractPythonIdentifiers = (code: string): string[] => {
    const cleaned = (code || '')
        .replace(/('''[\s\S]*?'''|"""[\s\S]*?""")/g, ' ')
        .replace(/('(?:[^'\\\n]|\\.)*'|"(?:[^"\\\n]|\\.)*")/g, ' ')
        .replace(/#.*$/gm, ' ')
    const identifiers = new Set<string>()
    const identifierPattern = /(?<![\w.])[A-Za-z_]\w*/g
    let match = identifierPattern.exec(cleaned)
    while (match) {
        identifiers.add(match[0])
        match = identifierPattern.exec(cleaned)
    }
    return Array.from(identifiers)
}

export const resolveSqlV2ReturnVariable = (returnVariable: string): string => {
    return returnVariable.trim() || 'sql_df'
}

// A dataframe name is referenced as a bare SQL table name and becomes a Python variable, so
// only a plain identifier can ever be referenced. A blank name is display-only; a non-blank
// but invalid one (e.g. `people-df`) is treated the same way for collection — it exports
// nothing, so it never pollutes the dependency graph or schema browser with an unusable name.
const SQL_V2_FRAME_NAME = /^[A-Za-z_][A-Za-z0-9_]*$/
export const isReferenceableSqlV2FrameName = (returnVariable: string): boolean =>
    SQL_V2_FRAME_NAME.test(returnVariable.trim())

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
    let resolvedReturnVariable = isReferenceableSqlV2FrameName(fallbackReturnVariable)
        ? resolveSqlV2ReturnVariable(fallbackReturnVariable)
        : ''
    let resolvedFromNodes = false

    nodes.forEach((node) => {
        // An unnamed or invalid cell binds no dataframe: it claims no name and needs none reserved.
        if (!node.returnVariable) {
            if (node.nodeId === nodeId) {
                resolvedReturnVariable = ''
                resolvedFromNodes = true
            }
            return
        }
        const baseReturnVariable = resolveSqlV2ReturnVariable(node.returnVariable)
        const uniqueReturnVariable = buildUniqueSqlV2ReturnVariable(baseReturnVariable, used)
        used.add(normalizeSqlIdentifier(uniqueReturnVariable))

        if (node.nodeId === nodeId) {
            resolvedReturnVariable = uniqueReturnVariable
            resolvedFromNodes = true
        }
    })

    if (!resolvedFromNodes && resolvedReturnVariable) {
        resolvedReturnVariable = buildUniqueSqlV2ReturnVariable(resolvedReturnVariable, used)
    }

    return resolvedReturnVariable
}

// Markdown notebooks hold their cells as component tags inside a single markdown attribute,
// so walking the tiptap JSON alone never finds them. Expand the given cell tag into
// tiptap-shaped nodes so the collectors and the dependency graph see the same cells in both
// notebook formats. Scoped to the revamped-notebook cell types (SQLV2 + kernel Python):
// expanding the other node types would change their (markdown-blind) summaries and naming.
// Each collector that expands a markdown notebook parses the same markdown string, so one edit
// parses the whole document once per collector. Cache the parse on the node object. Every
// collector in a recompute reads the same content node, so they share one parse. The next edit
// builds a new content node, so the old entry drops with it — the parse never goes stale.
const parsedMarkdownNotebookByNode = new WeakMap<object, ReturnType<typeof parseMarkdownNotebook>>()

const parseMarkdownNotebookNodeCached = (node: {
    attrs: { markdown: string }
}): ReturnType<typeof parseMarkdownNotebook> => {
    const cached = parsedMarkdownNotebookByNode.get(node)
    if (cached) {
        return cached
    }
    const parsed = parseMarkdownNotebook(node.attrs.markdown)
    parsedMarkdownNotebookByNode.set(node, parsed)
    return parsed
}

const expandMarkdownNotebookNodesOfTypes = (node: any, nodeTypes: NotebookNodeType[]): JSONContent[] => {
    if (typeof node?.attrs?.markdown !== 'string') {
        return []
    }
    // Keyed by tag so one pass over the parsed blocks can expand several cell types at once,
    // keeping them in document order — collecting each type separately would group all the SQL
    // cells before all the Python ones.
    const nodeTypeByTag = new Map<string, NotebookNodeType>()
    for (const nodeType of nodeTypes) {
        const tag = NOTEBOOK_NODE_TYPE_TO_MARKDOWN_TAG[nodeType]
        if (tag) {
            nodeTypeByTag.set(tag, nodeType)
            if (nodeType === NotebookNodeType.Query) {
                nodeTypeByTag.set('Insight', nodeType)
            }
        }
    }
    return parseMarkdownNotebookNodeCached(node).nodes.flatMap((block): JSONContent[] => {
        if (block.type !== 'component') {
            return []
        }
        const nodeType = nodeTypeByTag.get(block.tagName)
        if (!nodeType) {
            return []
        }
        return [
            {
                type: nodeType,
                attrs: {
                    ...block.props,
                    ...(nodeType === NotebookNodeType.SQLV2 ? getSqlV2PropsFromQueryProp(block.props) : null),
                    // Prefer the persisted nodeId prop: the parsed block id is a content
                    // fingerprint, which drifts from the live cell id as soon as any prop
                    // changes (running a cell writes runId/result into its props).
                    nodeId:
                        typeof block.props.nodeId === 'string' && block.props.nodeId ? block.props.nodeId : block.id,
                },
            },
        ]
    })
}

const expandMarkdownNotebookNodesOfType = (node: any, nodeType: NotebookNodeType): JSONContent[] =>
    expandMarkdownNotebookNodesOfTypes(node, [nodeType])

export interface NotebookDataframeNode {
    node: JSONContent
    nodeId: string
    nodeIndex: number
    returnVariable: string
    exportedName: string
}

const dataframeNodesByContent = new WeakMap<object, NotebookDataframeNode[]>()

export function collectNotebookDataframeNodes(content?: JSONContent | null): NotebookDataframeNode[] {
    if (!content || typeof content !== 'object') {
        return []
    }
    const cached = dataframeNodesByContent.get(content)
    if (cached) {
        return cached
    }
    const nodes: NotebookDataframeNode[] = []
    const counters: Record<string, number> = {}
    const walk = (node: JSONContent): void => {
        if (!node || typeof node !== 'object') {
            return
        }
        if (
            (node.type === NotebookNodeType.SQLV2 ||
                node.type === NotebookNodeType.PythonV2 ||
                isInsightDataframeNode(node)) &&
            node.attrs?.nodeId
        ) {
            const type = node.type ?? ''
            counters[type] = (counters[type] ?? 0) + 1
            nodes.push({
                node,
                nodeId: node.attrs.nodeId,
                nodeIndex: counters[type],
                returnVariable: '',
                exportedName: '',
            })
        }
        if (node.type === NotebookNodeType.MarkdownNotebook) {
            expandMarkdownNotebookNodesOfTypes(node, [
                NotebookNodeType.SQLV2,
                NotebookNodeType.PythonV2,
                NotebookNodeType.Query,
            ]).forEach(walk)
        }
        node.content?.forEach(walk)
    }
    walk(content)
    const used = new Set<string>()
    for (const type of [NotebookNodeType.SQLV2, NotebookNodeType.Query, NotebookNodeType.PythonV2]) {
        for (const entry of nodes.filter(({ node }) => node.type === type)) {
            const attrs = entry.node.attrs ?? {}
            const baseName =
                typeof attrs.returnVariable === 'string'
                    ? attrs.returnVariable.trim()
                    : type === NotebookNodeType.Query
                      ? 'insight_df'
                      : type === NotebookNodeType.SQLV2
                        ? 'sql_df'
                        : 'df'
            entry.returnVariable = baseName
            if (
                !isReferenceableSqlV2FrameName(baseName) ||
                (type === NotebookNodeType.Query && !attrs.dataframeQuery?.trim())
            ) {
                continue
            }
            if (type === NotebookNodeType.PythonV2 && used.has(normalizeSqlIdentifier(baseName))) {
                continue
            }
            entry.returnVariable =
                type === NotebookNodeType.PythonV2 ? baseName : buildUniqueSqlV2ReturnVariable(baseName, used)
            entry.exportedName = entry.returnVariable
            used.add(normalizeSqlIdentifier(entry.returnVariable))
        }
    }
    for (const entry of nodes.filter(
        ({ node }) => node.type === NotebookNodeType.Query && !node.attrs?.dataframeQuery?.trim()
    )) {
        if (isReferenceableSqlV2FrameName(entry.returnVariable)) {
            entry.returnVariable = buildUniqueSqlV2ReturnVariable(entry.returnVariable, used)
            used.add(normalizeSqlIdentifier(entry.returnVariable))
        }
    }
    dataframeNodesByContent.set(content, nodes)
    return nodes
}

export const collectSqlV2Nodes = (content?: JSONContent | null): SqlV2NodeSummary[] =>
    collectNotebookDataframeNodes(content)
        .filter(
            ({ node, exportedName }) =>
                node.type === NotebookNodeType.SQLV2 || (node.type === NotebookNodeType.Query && !!exportedName)
        )
        .map(({ node, nodeId, nodeIndex, exportedName }) => {
            const code =
                node.type === NotebookNodeType.Query ? (node.attrs?.dataframeQuery ?? '') : (node.attrs?.code ?? '')
            return {
                nodeId,
                code,
                returnVariable: exportedName,
                tablesUsed: extractDuckSqlTables(code),
                sqlV2Index: nodeIndex,
                title: node.attrs?.title ?? '',
            }
        })

export type NotebookFrameNodeSummary = {
    nodeId: string
    name: string
    /**
     * Which cell produced it, which decides where the data lives. A SQL cell that pushed to
     * ClickHouse can be referenced again from SQL with no kernel at all (it is re-inlined as a
     * CTE); a Python cell's output only exists inside the kernel.
     */
    nodeType: 'sql' | 'python'
    /** [column name, type] pairs from the last run, empty when the cell has never produced a frame. */
    columns: [string, string][]
    rowCount: number | null
    /**
     * The cell has a stored result. A cell that has never run can't be referenced at all — the
     * backend resolves refs to the latest DONE run — but a cell that ran and produced no frame
     * (its code binds nothing, or it was DDL) is a different story, and `columns` tells them apart.
     */
    hasRun: boolean
    /** Empty for a cell nobody has written yet, which binds nothing worth listing. */
    code: string
}

const frameNodeColumns = (result: any): [string, string][] => {
    if (!result || !Array.isArray(result.types)) {
        return []
    }
    return result.types
        .filter((pair: unknown): pair is [string, string] => Array.isArray(pair) && pair.length >= 2)
        .map(([name, type]: [string, string]) => [String(name), String(type)] as [string, string])
}

/**
 * Every cell in a revamped notebook that binds a name other cells can reference, in document
 * order, with the shape of its last run.
 *
 * This is the notebook's own record, not the kernel's: a SQL cell's output never enters the
 * kernel unless something materializes it, so the kernel's catalog alone cannot see it.
 * Names follow each collector's existing rules — SQL names disambiguated as the dependency
 * graph does, Python names left as the raw kernel variables.
 */
export const collectNotebookFrameNodes = (content?: JSONContent | null): NotebookFrameNodeSummary[] =>
    collectNotebookDataframeNodes(content)
        .filter(({ exportedName }) => !!exportedName)
        .map(({ node, nodeId, exportedName }) => ({
            nodeId,
            name: exportedName,
            nodeType: node.type === NotebookNodeType.PythonV2 ? 'python' : 'sql',
            columns: frameNodeColumns(node.attrs?.result),
            rowCount: node.attrs?.result?.row_count ?? null,
            hasRun: !!node.attrs?.result,
            code: node.type === NotebookNodeType.Query ? (node.attrs?.dataframeQuery ?? '') : (node.attrs?.code ?? ''),
        }))

export type PythonKernelNodeSummary = {
    nodeId: string
    returnVariable: string
}

// Kernel-run Python cells (revamped notebooks): each binds its result to `returnVariable` in
// the kernel namespace. Unlike the SQL collectors the names are NOT disambiguated — they are
// exactly the kernel variables, so a duplicated returnVariable means last-run-wins, matching
// kernel semantics. A blank name is a display-only cell that binds nothing (see the SQLV2
// collector); only a missing attribute takes the legacy 'df' default. Markdown-aware because
// revamped markdown notebooks store their cells as `<PythonV2 …/>` component tags.
export const collectPythonKernelNodes = (content?: JSONContent | null): PythonKernelNodeSummary[] => {
    if (!content || typeof content !== 'object') {
        return []
    }

    const nodes: PythonKernelNodeSummary[] = []

    const walk = (node: any): void => {
        if (!node || typeof node !== 'object') {
            return
        }
        if (node.type === NotebookNodeType.PythonV2) {
            const attrs = node.attrs ?? {}
            const returnVariable = typeof attrs.returnVariable === 'string' ? attrs.returnVariable.trim() : 'df'
            nodes.push({ nodeId: attrs.nodeId ?? '', returnVariable })
        }
        if (node.type === NotebookNodeType.MarkdownNotebook) {
            expandMarkdownNotebookNodesOfType(node, NotebookNodeType.PythonV2).forEach(walk)
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

const matchesUsage = (exportName: string, usageName: string): boolean => exportName === usageName

export type NotebookDependencyDirection = 'upstream' | 'downstream'

/** Transitive closure of a node's dependencies (or dependents), including the start node. */
export const collectDependencyNodeIds = (
    dependencyGraph: NotebookDependencyGraph,
    startNodeId: string,
    direction: NotebookDependencyDirection
): Set<string> => {
    const visited = new Set<string>()
    if (!startNodeId || !dependencyGraph.nodesById[startNodeId]) {
        return visited
    }

    const stack = [startNodeId]

    while (stack.length > 0) {
        const currentId = stack.pop()
        if (!currentId || visited.has(currentId)) {
            continue
        }
        visited.add(currentId)

        if (direction === 'upstream') {
            const sources = Object.values(dependencyGraph.upstreamSourcesByNode[currentId] ?? {})
            sources.forEach((source) => {
                if (source.nodeId && !visited.has(source.nodeId)) {
                    stack.push(source.nodeId)
                }
            })
        } else {
            const downstreamGroups = Object.values(dependencyGraph.downstreamUsageByNode[currentId] ?? {})
            downstreamGroups.flat().forEach((usage) => {
                if (usage.nodeId && !visited.has(usage.nodeId)) {
                    stack.push(usage.nodeId)
                }
            })
        }
    }

    return visited
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

    const nodes: NotebookDependencyNode[] = collectNotebookDataframeNodes(content).map(
        ({ node, nodeId, nodeIndex, returnVariable, exportedName }) => {
            const attrs = node.attrs ?? {}
            const code = node.type === NotebookNodeType.Query ? (attrs.dataframeQuery ?? '') : (attrs.code ?? '')
            const connectionId =
                typeof attrs.connectionId === 'string' && attrs.connectionId ? attrs.connectionId : null
            return {
                nodeId,
                nodeType: node.type as NotebookNodeType,
                nodeIndex,
                title: attrs.title ?? '',
                exports: exportedName ? [exportedName] : [],
                uses:
                    node.type === NotebookNodeType.Query
                        ? []
                        : node.type === NotebookNodeType.PythonV2
                          ? extractPythonIdentifiers(code)
                          : extractDuckSqlTables(code),
                code,
                returnVariable,
                connectionId,
                sendRawQuery: !!connectionId && !!attrs.sendRawQuery,
            }
        }
    )

    const nodesById = nodes.reduce<Record<string, NotebookDependencyNode>>((acc, node) => {
        if (node.nodeId) {
            acc[node.nodeId] = node
        }
        return acc
    }, {})

    const upstreamSourcesByNode: Record<string, Record<string, NotebookDependencyUsage>> = {}
    const downstreamUsageByNode: Record<string, Record<string, NotebookDependencyUsage[]>> = {}

    nodes.forEach((node) => {
        const upstreamNodes = nodes.filter((candidate) => candidate.nodeId !== node.nodeId)
        const downstreamNodes = upstreamNodes

        const upstreamSources = node.uses.reduce<Record<string, NotebookDependencyUsage>>((acc, usageName) => {
            const source = upstreamNodes.find((upstreamNode) =>
                upstreamNode.exports.some((exportName) => matchesUsage(exportName, usageName))
            )
            if (source) {
                acc[usageName] = buildDependencyUsage(source)
            }
            return acc
        }, {})

        const downstreamUsage = node.exports.reduce<Record<string, NotebookDependencyUsage[]>>((acc, exportName) => {
            acc[exportName] = downstreamNodes
                .filter((downstreamNode) =>
                    downstreamNode.uses.some((usageName) => matchesUsage(exportName, usageName))
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
