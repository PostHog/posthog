import {
    BuiltLogic,
    actions,
    afterMount,
    beforeUnmount,
    connect,
    kea,
    key,
    listeners,
    path,
    props,
    reducers,
    selectors,
} from 'kea'
import posthog from 'posthog-js'

import { LemonMenuItems } from '@posthog/lemon-ui'

import api from 'lib/api'
import { JSONContent, RichContentNode } from 'lib/components/RichContentEditor/types'
import { hashCodeForString } from 'lib/utils'

import { isHogQLQuery, isNodeWithSource } from '~/queries/utils'

import { notebookLogicType } from '../Notebook/notebookLogicType'
import {
    CustomNotebookNodeAttributes,
    NotebookNodeAction,
    NotebookNodeAttributeProperties,
    NotebookNodeAttributes,
    NotebookNodeResource,
    NotebookNodeSettings,
    NotebookNodeSettingsPlacement,
    NotebookNodeType,
} from '../types'
import { NotebookNodeMessages, NotebookNodeMessagesListeners } from './messaging/notebook-node-messages'
import {
    type DuckSqlNodeSummary,
    type NotebookDependencyGraph,
    type NotebookDependencyNode,
    type NotebookDependencyUsage,
    getUniqueDuckSqlReturnVariable,
    resolveDuckSqlReturnVariable,
} from './notebookNodeContent'
import type { notebookNodeLogicType } from './notebookNodeLogicType'
import {
    NotebookDataframeResult,
    PythonExecutionResult,
    PythonExecutionVariable,
    PythonKernelExecuteResponse,
    buildPythonExecutionError,
    buildPythonExecutionResult,
} from './pythonExecution'

export type PythonRunMode = 'auto' | 'cell_upstream' | 'cell' | 'cell_downstream'
export type DuckSqlRunMode = 'auto' | 'cell_upstream' | 'cell' | 'cell_downstream'

type RunPythonCellParams = {
    notebookId: string
    code: string
    exportedGlobals: { name: string; type: string }[]
    updateAttributes: (attributes: Partial<NotebookNodeAttributes<any>>) => void
    setPythonRunLoading: (loading: boolean) => void
    executionSandboxId: string | null
}

type RunDuckSqlCellParams = {
    notebookId: string
    code: string
    returnVariable: string
    pageSize: number
    updateAttributes: (attributes: Partial<NotebookNodeAttributes<any>>) => void
    setDuckSqlRunLoading: (loading: boolean) => void
    executionSandboxId: string | null
}

const isSqlQueryNode = (nodeAttributes: NotebookNodeAttributes<any>): boolean => {
    const query = nodeAttributes?.query
    if (!query) {
        return false
    }
    if (isNodeWithSource(query)) {
        return isHogQLQuery(query.source)
    }
    return false
}

const DEFAULT_DATAFRAME_PAGE_SIZE = 10

const buildDuckSqlCode = (code: string, returnVariable: string, pageSize: number): string => {
    const resolvedReturnVariable = resolveDuckSqlReturnVariable(returnVariable)
    const sqlLiteral = JSON.stringify(code ?? '')
    const tableNameLiteral = JSON.stringify(resolvedReturnVariable)
    const previewPageSize = Math.max(1, pageSize || DEFAULT_DATAFRAME_PAGE_SIZE)
    return (
        `import json\n` +
        `${resolvedReturnVariable} = duck_execute(${sqlLiteral})\n` +
        `duck_save_table(${tableNameLiteral}, ${resolvedReturnVariable})\n` +
        `json.dumps(notebook_dataframe_page(${resolvedReturnVariable}, offset=0, limit=${previewPageSize}))`
    )
}

type DependencyRunDirection = 'upstream' | 'downstream'

const collectDependencyNodeIds = (
    dependencyGraph: NotebookDependencyGraph,
    startNodeId: string,
    direction: DependencyRunDirection
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

const getDependencyNodesForRun = (
    dependencyGraph: NotebookDependencyGraph,
    startNodeId: string,
    direction: DependencyRunDirection
): NotebookDependencyNode[] => {
    const nodeIds = collectDependencyNodeIds(dependencyGraph, startNodeId, direction)
    if (nodeIds.size === 0) {
        return []
    }

    return dependencyGraph.nodes.filter((node) => nodeIds.has(node.nodeId))
}

const getDependencyEntriesWithLogic = ({
    dependencyGraph,
    nodeId,
    direction,
    notebookLogic,
}: {
    dependencyGraph: NotebookDependencyGraph
    nodeId: string
    direction: DependencyRunDirection
    notebookLogic: BuiltLogic<notebookLogicType>
}): { node: NotebookDependencyNode; nodeLogic: BuiltLogic<notebookNodeLogicType> }[] => {
    const nodesToRun = getDependencyNodesForRun(dependencyGraph, nodeId, direction)
    if (nodesToRun.length === 0) {
        return []
    }

    return nodesToRun
        .map((node) => ({
            node,
            nodeLogic: notebookLogic.values.findNodeLogicById(node.nodeId),
        }))
        .filter(
            (
                entry
            ): entry is {
                node: (typeof nodesToRun)[number]
                nodeLogic: BuiltLogic<notebookNodeLogicType>
            } => !!entry.nodeLogic
        )
}

const isPythonExecutionFresh = (nodeLogic: BuiltLogic<notebookNodeLogicType>, code: string): boolean => {
    const { pythonExecutionCodeHash, pythonExecution, pythonExecutionSandboxId } = nodeLogic.values.nodeAttributes
    const codeHash = hashCodeForString(code)
    const kernelSandboxId = nodeLogic.values.kernelInfo?.sandbox_id ?? null
    const kernelIsRunning = nodeLogic.values.kernelInfo?.status === 'running'
    const sandboxMatches =
        pythonExecutionSandboxId && kernelSandboxId !== null && pythonExecutionSandboxId === kernelSandboxId
    return (
        pythonExecutionCodeHash &&
        pythonExecutionCodeHash === codeHash &&
        pythonExecution?.status === 'ok' &&
        sandboxMatches &&
        kernelIsRunning
    )
}

const isDuckSqlExecutionFresh = (
    nodeLogic: BuiltLogic<notebookNodeLogicType>,
    code: string,
    returnVariable: string
): boolean => {
    const { duckExecutionCodeHash, duckExecution, duckExecutionSandboxId } = nodeLogic.values.nodeAttributes
    const codeHash = hashCodeForString(`${code}\n${returnVariable}`)
    const kernelSandboxId = nodeLogic.values.kernelInfo?.sandbox_id ?? null
    const kernelIsRunning = nodeLogic.values.kernelInfo?.status === 'running'
    const sandboxMatches =
        duckExecutionSandboxId && kernelSandboxId !== null && duckExecutionSandboxId === kernelSandboxId
    return (
        duckExecutionCodeHash &&
        duckExecutionCodeHash === codeHash &&
        duckExecution?.status === 'ok' &&
        sandboxMatches &&
        kernelIsRunning
    )
}

const setDependencyNodeQueued = (
    nodeLogic: BuiltLogic<notebookNodeLogicType>,
    nodeType: NotebookNodeType,
    queued: boolean
): void => {
    if (nodeType === NotebookNodeType.Python) {
        nodeLogic.actions.setPythonRunQueued(queued)
        return
    }
    if (nodeType === NotebookNodeType.DuckSQL) {
        nodeLogic.actions.setDuckSqlRunQueued(queued)
    }
}

const runDependencyNodes = async ({
    entries,
    notebookId,
    mode,
    duckSqlNodeSummaries,
    currentNodeId,
    skipDataframeVariableUpdateForNodeId,
}: {
    entries: { node: NotebookDependencyNode; nodeLogic: BuiltLogic<notebookNodeLogicType> }[]
    notebookId: string
    mode: PythonRunMode | DuckSqlRunMode
    duckSqlNodeSummaries: DuckSqlNodeSummary[]
    currentNodeId: string
    skipDataframeVariableUpdateForNodeId?: string
}): Promise<void> => {
    entries.forEach(({ node, nodeLogic }) => setDependencyNodeQueued(nodeLogic, node.nodeType, true))

    try {
        for (const { node, nodeLogic } of entries) {
            setDependencyNodeQueued(nodeLogic, node.nodeType, false)
            if (node.nodeType === NotebookNodeType.Python) {
                const nodeAttributes = nodeLogic.values.nodeAttributes as {
                    code?: string
                    pythonExecutionSandboxId?: string | null
                }
                const nodeCode = nodeAttributes.code ?? node.code ?? ''
                const executionSandboxId =
                    nodeLogic.values.kernelInfo?.sandbox_id ?? nodeAttributes.pythonExecutionSandboxId ?? null
                if (mode === 'auto' && node.nodeId !== currentNodeId && isPythonExecutionFresh(nodeLogic, nodeCode)) {
                    continue
                }
                const { executed, execution } = await runPythonCell({
                    notebookId,
                    code: nodeCode,
                    exportedGlobals: nodeLogic.values.exportedGlobals,
                    updateAttributes: nodeLogic.actions.updateAttributes,
                    setPythonRunLoading: nodeLogic.actions.setPythonRunLoading,
                    executionSandboxId,
                })

                const isSuccess = executed && execution?.status === 'ok'
                if (isSuccess) {
                    const dataframeVariable = findDataframeVariable(execution?.variables)
                    nodeLogic.actions.setDataframeVariableName(dataframeVariable)
                } else {
                    nodeLogic.actions.setDataframeVariableName(null)
                }
                if (!isSuccess) {
                    break
                }
                continue
            }

            if (node.nodeType === NotebookNodeType.DuckSQL) {
                const nodeAttributes = nodeLogic.values.nodeAttributes as {
                    code?: string
                    returnVariable?: string
                    duckExecutionSandboxId?: string | null
                }
                const nodeCode = nodeAttributes.code ?? node.code ?? ''
                const nodeReturnVariable = getUniqueDuckSqlReturnVariable(
                    duckSqlNodeSummaries,
                    node.nodeId,
                    nodeAttributes.returnVariable ?? node.returnVariable ?? 'duck_df'
                )
                const executionSandboxId =
                    nodeLogic.values.kernelInfo?.sandbox_id ?? nodeAttributes.duckExecutionSandboxId ?? null
                if (
                    mode === 'auto' &&
                    node.nodeId !== currentNodeId &&
                    isDuckSqlExecutionFresh(nodeLogic, nodeCode, nodeReturnVariable)
                ) {
                    continue
                }
                const { executed, execution } = await runDuckSqlCell({
                    notebookId,
                    code: nodeCode,
                    returnVariable: nodeReturnVariable,
                    pageSize: nodeLogic.values.dataframePageSize,
                    updateAttributes: nodeLogic.actions.updateAttributes,
                    setDuckSqlRunLoading: nodeLogic.actions.setDuckSqlRunLoading,
                    executionSandboxId,
                })

                const isSuccess = executed && execution?.status === 'ok'
                if (isSuccess) {
                    const previewResult = parseDataframePreview(execution?.result)
                    const shouldUpdateDataframeVariable =
                        node.nodeId !== skipDataframeVariableUpdateForNodeId || !nodeLogic.values.dataframeVariableName
                    if (shouldUpdateDataframeVariable) {
                        nodeLogic.actions.setDataframeVariableName(
                            nodeLogic.values.duckSqlReturnVariable,
                            previewResult
                        )
                    }
                } else {
                    nodeLogic.actions.setDataframeVariableName(null)
                }
                if (!isSuccess) {
                    break
                }
            }
        }
    } finally {
        entries.forEach(({ node, nodeLogic }) => setDependencyNodeQueued(nodeLogic, node.nodeType, false))
    }
}

const runPythonCell = async ({
    notebookId,
    code,
    exportedGlobals,
    updateAttributes,
    setPythonRunLoading,
    executionSandboxId,
}: RunPythonCellParams): Promise<{ executed: boolean; execution: PythonExecutionResult | null }> => {
    setPythonRunLoading(true)
    try {
        const execution = (await api.notebooks.kernelExecute(notebookId, {
            code,
            return_variables: exportedGlobals.length > 0,
        })) as PythonKernelExecuteResponse

        const executionResult = buildPythonExecutionResult(execution, exportedGlobals)
        const runtimeSandboxId = execution.kernel_runtime?.sandbox_id ?? executionSandboxId
        updateAttributes({
            pythonExecution: executionResult,
            pythonExecutionCodeHash: hashCodeForString(code),
            pythonExecutionSandboxId: runtimeSandboxId,
        })
        return { executed: true, execution: executionResult }
    } catch (error) {
        const message = error instanceof Error ? error.message : 'Failed to run Python cell.'
        const executionResult = buildPythonExecutionError(message, exportedGlobals)
        updateAttributes({
            pythonExecution: executionResult,
            pythonExecutionCodeHash: hashCodeForString(code),
            pythonExecutionSandboxId: executionSandboxId,
        })
        return { executed: false, execution: executionResult }
    } finally {
        setPythonRunLoading(false)
    }
}

const runDuckSqlCell = async ({
    notebookId,
    code,
    returnVariable,
    pageSize,
    updateAttributes,
    setDuckSqlRunLoading,
    executionSandboxId,
}: RunDuckSqlCellParams): Promise<{ executed: boolean; execution: PythonExecutionResult | null }> => {
    setDuckSqlRunLoading(true)
    const resolvedReturnVariable = resolveDuckSqlReturnVariable(returnVariable)
    const executionCode = buildDuckSqlCode(code, returnVariable, pageSize)
    try {
        const execution = (await api.notebooks.kernelExecute(notebookId, {
            code: executionCode,
            return_variables: true,
        })) as PythonKernelExecuteResponse

        const executionResult = buildPythonExecutionResult(execution, [
            { name: resolvedReturnVariable, type: 'DataFrame' },
        ])
        const runtimeSandboxId = execution.kernel_runtime?.sandbox_id ?? executionSandboxId
        updateAttributes({
            duckExecution: executionResult,
            duckExecutionCodeHash: hashCodeForString(`${code}\n${resolvedReturnVariable}`),
            duckExecutionSandboxId: runtimeSandboxId,
        })
        return { executed: true, execution: executionResult }
    } catch (error) {
        const message = error instanceof Error ? error.message : 'Failed to run SQL (duckdb) query.'
        const executionResult = buildPythonExecutionError(message, [
            { name: resolvedReturnVariable, type: 'DataFrame' },
        ])
        updateAttributes({
            duckExecution: executionResult,
            duckExecutionCodeHash: hashCodeForString(`${code}\n${resolvedReturnVariable}`),
            duckExecutionSandboxId: executionSandboxId,
        })
        return { executed: false, execution: executionResult }
    } finally {
        setDuckSqlRunLoading(false)
    }
}

const findDataframeVariable = (variables?: PythonExecutionVariable[]): string | null => {
    if (!variables) {
        return null
    }
    const match = variables.find((variable) => variable.type?.toLowerCase() === 'dataframe')
    return match?.name ?? null
}

const parseDataframePreview = (preview?: string | null): NotebookDataframeResult | null => {
    if (!preview) {
        return null
    }
    const trimmed = preview.trim()
    if (!trimmed) {
        return null
    }
    const candidates = [trimmed]
    if ((trimmed.startsWith('"') && trimmed.endsWith('"')) || (trimmed.startsWith("'") && trimmed.endsWith("'"))) {
        candidates.push(trimmed.slice(1, -1))
    }

    for (const candidate of candidates) {
        try {
            const parsed = JSON.parse(candidate) as {
                columns?: string[]
                rows?: Record<string, any>[]
                rowCount?: number
                row_count?: number
            }
            if (!parsed || typeof parsed !== 'object') {
                continue
            }
            const columns = Array.isArray(parsed.columns) ? parsed.columns : []
            const rows = Array.isArray(parsed.rows) ? parsed.rows : []
            const rowCount = parsed.rowCount || parsed.row_count || rows.length
            return {
                columns,
                rows,
                rowCount,
            }
        } catch {}
    }
    return null
}

export type NotebookNodeLogicProps = {
    nodeType: NotebookNodeType
    notebookLogic: BuiltLogic<notebookLogicType>
    getPos?: () => number | undefined
    resizeable?: boolean | ((attributes: CustomNotebookNodeAttributes) => boolean)
    Settings?: NotebookNodeSettings
    messageListeners?: NotebookNodeMessagesListeners
    startExpanded?: boolean
    titlePlaceholder: string
    settingsPlacement?: NotebookNodeSettingsPlacement
} & NotebookNodeAttributeProperties<any>

export const notebookNodeLogic = kea<notebookNodeLogicType>([
    props({} as NotebookNodeLogicProps),
    path((key) => ['scenes', 'notebooks', 'Notebook', 'Nodes', 'notebookNodeLogic', key]),
    key(({ attributes }) => attributes.nodeId || 'no-node-id-set'),
    actions({
        setExpanded: (expanded: boolean) => ({ expanded }),
        setResizeable: (resizeable: boolean) => ({ resizeable }),
        setActions: (actions: (NotebookNodeAction | undefined)[]) => ({ actions }),
        setMenuItems: (menuItems: LemonMenuItems | null) => ({ menuItems }),
        insertAfter: (content: JSONContent) => ({ content }),
        insertAfterLastNodeOfType: (nodeType: string, content: JSONContent) => ({ content, nodeType }),
        updateAttributes: (attributes: Partial<NotebookNodeAttributes<any>>) => ({ attributes }),
        insertOrSelectNextLine: true,
        setPreviousNode: (node: RichContentNode | null) => ({ node }),
        setNextNode: (node: RichContentNode | null) => ({ node }),
        deleteNode: true,
        selectNode: (scroll?: boolean) => ({ scroll }),
        toggleEditing: (visible?: boolean) => ({ visible }),
        scrollIntoView: true,
        initializeNode: true,
        setMessageListeners: (listeners: NotebookNodeMessagesListeners) => ({ listeners }),
        setTitlePlaceholder: (titlePlaceholder: string) => ({ titlePlaceholder }),
        setRef: (ref: HTMLElement | null) => ({ ref }),
        toggleEditingTitle: (editing?: boolean) => ({ editing }),
        copyToClipboard: true,
        convertToBacklink: (href: string) => ({ href }),
        navigateToNode: (nodeId: string) => ({ nodeId }),
        runPythonNode: (payload: { code: string }) => payload,
        runPythonNodeWithMode: (payload: { mode: PythonRunMode }) => payload,
        setPythonRunLoading: (loading: boolean) => ({ loading }),
        setPythonRunQueued: (queued: boolean) => ({ queued }),
        runDuckSqlNode: true,
        runDuckSqlNodeWithMode: (payload: { mode: DuckSqlRunMode }) => payload,
        setDuckSqlRunLoading: (loading: boolean) => ({ loading }),
        setDuckSqlRunQueued: (queued: boolean) => ({ queued }),
        setDataframeVariableName: (variableName: string | null, initialResult?: NotebookDataframeResult | null) => ({
            variableName,
            initialResult,
        }),
        setDataframePage: (page: number) => ({ page }),
        setDataframePageSize: (pageSize: number) => ({ pageSize }),
        loadDataframePage: (payload: { variableName: string; pageSize?: number }) => payload,
        setDataframeResult: (result: NotebookDataframeResult | null) => ({ result }),
        setDataframeLoading: (loading: boolean) => ({ loading }),
        setDataframeError: (error: string | null) => ({ error }),
        resetDataframeResults: true,
    }),

    connect((props: NotebookNodeLogicProps) => ({
        actions: [props.notebookLogic, ['onUpdateEditor', 'setTextSelection']],
        values: [
            props.notebookLogic,
            [
                'editor',
                'isEditable',
                'comments',
                'pythonNodeSummaries',
                'duckSqlNodeSummaries',
                'dependencyGraph',
                'notebook',
                'kernelInfo',
            ],
        ],
    })),

    reducers(({ props }) => ({
        ref: [
            null as HTMLElement | null,
            {
                setRef: (_, { ref }) => ref,
            },
        ],
        expanded: [
            props.startExpanded ?? true,
            {
                setExpanded: (_, { expanded }) => expanded,
            },
        ],
        resizeable: [
            false,
            {
                setResizeable: (_, { resizeable }) => resizeable,
            },
        ],
        previousNode: [
            null as RichContentNode | null,
            {
                setPreviousNode: (_, { node }) => node,
            },
        ],
        nextNode: [
            null as RichContentNode | null,
            {
                setNextNode: (_, { node }) => node,
            },
        ],
        actions: [
            [] as NotebookNodeAction[],
            {
                setActions: (_, { actions }) => actions.filter((x) => !!x) as NotebookNodeAction[],
            },
        ],
        customMenuItems: [
            null as LemonMenuItems | null,
            {
                setMenuItems: (_, { menuItems }) => menuItems,
            },
        ],
        messageListeners: [
            props.messageListeners as NotebookNodeMessagesListeners,
            {
                setMessageListeners: (_, { listeners }) => listeners,
            },
        ],
        titlePlaceholder: [
            props.titlePlaceholder,
            {
                setTitlePlaceholder: (_, { titlePlaceholder }) => titlePlaceholder,
            },
        ],
        isEditingTitle: [
            false,
            {
                toggleEditingTitle: (state, { editing }) => (typeof editing === 'boolean' ? editing : !state),
            },
        ],
        pythonRunLoading: [
            false,
            {
                setPythonRunLoading: (_, { loading }) => loading,
            },
        ],
        pythonRunQueued: [
            false,
            {
                setPythonRunQueued: (_, { queued }) => queued,
            },
        ],
        duckSqlRunLoading: [
            false,
            {
                setDuckSqlRunLoading: (_, { loading }) => loading,
            },
        ],
        duckSqlRunQueued: [
            false,
            {
                setDuckSqlRunQueued: (_, { queued }) => queued,
            },
        ],
        dataframeVariableName: [
            null as string | null,
            {
                setDataframeVariableName: (_, { variableName }) => variableName,
            },
        ],
        dataframePage: [
            1,
            {
                setDataframePage: (_, { page }) => page,
                setDataframePageSize: () => 1,
                resetDataframeResults: () => 1,
            },
        ],
        dataframePageSize: [
            DEFAULT_DATAFRAME_PAGE_SIZE as number,
            {
                setDataframePageSize: (_, { pageSize }) => pageSize,
            },
        ],
        dataframeResult: [
            null as NotebookDataframeResult | null,
            {
                setDataframeResult: (_, { result }) => result,
                resetDataframeResults: () => null,
            },
        ],
        dataframeLoading: [
            false,
            {
                setDataframeLoading: (_, { loading }) => loading,
                resetDataframeResults: () => false,
            },
        ],
        dataframeError: [
            null as string | null,
            {
                setDataframeError: (_, { error }) => error,
                resetDataframeResults: () => null,
            },
        ],
    })),

    selectors({
        notebookLogic: [(_, p) => [p.notebookLogic], (notebookLogic): BuiltLogic<notebookLogicType> => notebookLogic],
        nodeAttributes: [(_, p) => [p.attributes], (nodeAttributes): NotebookNodeAttributes<any> => nodeAttributes],
        nodeId: [
            (_, p) => [p.attributes],
            (nodeAttributes: NotebookNodeAttributes<any>): string => nodeAttributes.nodeId,
        ],
        nodeType: [(_, p) => [p.nodeType], (nodeType) => nodeType],
        Settings: [() => [(_, props) => props], (props): NotebookNodeSettings | null => props.Settings ?? null],
        settingsPlacement: [
            () => [(_, props) => props],
            (props): NotebookNodeSettingsPlacement => props.settingsPlacement ?? 'left',
        ],

        title: [
            (s) => [s.titlePlaceholder, s.nodeAttributes],
            (titlePlaceholder, nodeAttributes) => nodeAttributes.title || titlePlaceholder,
        ],
        // TODO: Fix the typing of nodeAttributes
        children: [(s) => [s.nodeAttributes], (nodeAttributes): NotebookNodeResource[] => nodeAttributes.children],

        exportedGlobals: [
            (s) => [s.nodeAttributes],
            (nodeAttributes): { name: string; type: string }[] => nodeAttributes.globalsExportedWithTypes ?? [],
        ],
        pythonExecution: [
            (s) => [s.nodeAttributes],
            (nodeAttributes): PythonExecutionResult | null => nodeAttributes.pythonExecution ?? null,
        ],
        displayedGlobals: [
            (s) => [s.exportedGlobals, s.pythonExecution],
            (exportedGlobals, pythonExecution): { name: string; type: string }[] => {
                if (!pythonExecution?.variables?.length) {
                    return exportedGlobals
                }

                const typeByName = new Map<string, string>(
                    pythonExecution.variables.map((variable: PythonExecutionVariable) => [variable.name, variable.type])
                )
                return exportedGlobals.map(({ name, type }) => ({
                    name,
                    type: typeByName.get(name) ?? type,
                }))
            },
        ],

        pythonNodeIndex: [
            (s) => [s.pythonNodeSummaries, s.nodeId],
            (pythonNodeSummaries, nodeId) => pythonNodeSummaries.findIndex((node) => node.nodeId === nodeId),
        ],
        duckSqlNodeIndex: [
            (s) => [s.duckSqlNodeSummaries, s.nodeId],
            (duckSqlNodeSummaries, nodeId) => duckSqlNodeSummaries.findIndex((node) => node.nodeId === nodeId),
        ],
        duckSqlReturnVariable: [
            (s) => [s.duckSqlNodeSummaries, s.nodeId, s.nodeAttributes],
            (duckSqlNodeSummaries, nodeId, nodeAttributes): string =>
                getUniqueDuckSqlReturnVariable(duckSqlNodeSummaries, nodeId, nodeAttributes.returnVariable ?? ''),
        ],
        dataframeRowCount: [(s) => [s.dataframeResult], (dataframeResult): number => dataframeResult?.rowCount ?? 0],
        duckSqlTablesUsed: [
            (s) => [s.dependencyGraph, s.nodeId],
            (dependencyGraph, nodeId): string[] => dependencyGraph.nodesById[nodeId]?.uses ?? [],
        ],
        duckSqlUpstreamTableSources: [
            (s) => [s.dependencyGraph, s.nodeId],
            (dependencyGraph, nodeId): Record<string, NotebookDependencyUsage> =>
                dependencyGraph.upstreamSourcesByNode[nodeId] ?? {},
        ],
        duckSqlReturnVariableUsage: [
            (s) => [s.dependencyGraph, s.nodeId, s.duckSqlReturnVariable],
            (dependencyGraph, nodeId, duckSqlReturnVariable): NotebookDependencyUsage[] =>
                dependencyGraph.downstreamUsageByNode[nodeId]?.[duckSqlReturnVariable] ?? [],
        ],

        usageByVariable: [
            (s) => [s.dependencyGraph, s.exportedGlobals, s.nodeId],
            (dependencyGraph, exportedGlobals, nodeId): Record<string, NotebookDependencyUsage[]> => {
                const usageMap: Record<string, NotebookDependencyUsage[]> = {}

                exportedGlobals.forEach(({ name }) => {
                    const usages = dependencyGraph.downstreamUsageByNode[nodeId]?.[name] ?? []
                    usageMap[name] = usages.filter((usage) => usage.nodeType === NotebookNodeType.Python)
                })

                return usageMap
            },
        ],

        sendMessage: [
            (s) => [s.messageListeners],
            (messageListeners) => {
                return <T extends keyof NotebookNodeMessages>(
                    message: T,
                    payload: NotebookNodeMessages[T]
                ): boolean => {
                    if (!messageListeners[message]) {
                        return false
                    }

                    messageListeners[message]?.(payload)
                    return true
                }
            },
        ],

        sourceComment: [
            (s) => [s.comments, s.nodeId],
            (comments, nodeId) =>
                comments &&
                comments.find(
                    (comment) => comment.item_context?.type === 'node' && comment.item_context?.id === nodeId
                ),
        ],
    }),

    listeners(({ actions, values, props }) => ({
        onUpdateEditor: async () => {
            if (!props.getPos) {
                return
            }
            const editor = values.notebookLogic.values.editor
            const pos = props.getPos()
            if (editor && pos) {
                const { previous, next } = editor.getAdjacentNodes(pos)
                actions.setPreviousNode(previous)
                actions.setNextNode(next)
            }
        },

        insertAfter: ({ content }) => {
            const pos = props.getPos?.()
            if (!pos) {
                return
            }
            const logic = values.notebookLogic
            logic.values.editor?.insertContentAfterNode(pos, content)
        },

        deleteNode: () => {
            const pos = props.getPos?.()
            if (!pos) {
                // TODO: somehow make this delete from the parent
                return
            }

            const logic = values.notebookLogic
            logic.values.editor?.deleteRange({ from: pos, to: pos + 1 }).run()
            if (values.notebookLogic.values.editingNodeIds[values.nodeId]) {
                values.notebookLogic.actions.setEditingNodeEditing(values.nodeId, false)
            }
        },

        selectNode: ({ scroll }) => {
            const pos = props.getPos?.()
            if (!pos) {
                return
            }
            const editor = values.notebookLogic.values.editor

            if (editor) {
                editor.setSelection(pos)
                if (scroll ?? true) {
                    editor.scrollToSelection()
                }
            }
        },

        navigateToNode: ({ nodeId }) => {
            const targetLogic = values.notebookLogic.values.findNodeLogicById(nodeId)
            targetLogic?.actions.selectNode()
        },

        scrollIntoView: () => {
            const pos = props.getPos?.()
            if (!pos) {
                return
            }
            values.editor?.scrollToPosition(pos)
        },

        insertAfterLastNodeOfType: ({ nodeType, content }) => {
            const insertionPosition = props.getPos?.()
            if (!insertionPosition) {
                return
            }
            values.notebookLogic.actions.insertAfterLastNodeOfType(nodeType, content, insertionPosition)
        },
        insertOrSelectNextLine: () => {
            const pos = props.getPos?.()
            if (!pos || !values.isEditable) {
                return
            }

            if (!values.nextNode || !values.nextNode.isTextblock) {
                actions.insertAfter({
                    type: 'paragraph',
                })
            } else {
                actions.setTextSelection(pos + 1)
            }
        },

        setExpanded: ({ expanded }) => {
            if (expanded) {
                posthog.capture('notebook node expanded', {
                    node_type: props.nodeType,
                    short_id: props.notebookLogic.props.shortId,
                })
            }
        },

        updateAttributes: ({ attributes }) => {
            props.updateAttributes(attributes)
        },
        toggleEditing: ({ visible }) => {
            const isEditing = values.notebookLogic.values.editingNodeIds[values.nodeId]
            const shouldShowThis = typeof visible === 'boolean' ? visible : !isEditing

            props.notebookLogic.actions.setEditingNodeEditing(values.nodeId, shouldShowThis)
            if (
                props.nodeType === NotebookNodeType.Python ||
                (props.nodeType === NotebookNodeType.Query && isSqlQueryNode(values.nodeAttributes)) ||
                props.nodeType === NotebookNodeType.DuckSQL
            ) {
                actions.updateAttributes({ showSettings: shouldShowThis })
            }
        },
        initializeNode: () => {
            const { __init } = values.nodeAttributes

            if (__init) {
                if (__init.expanded) {
                    actions.setExpanded(true)
                }
                if (__init.showSettings) {
                    actions.toggleEditing(true)
                }
                if (
                    (props.nodeType === NotebookNodeType.Python ||
                        (props.nodeType === NotebookNodeType.Query && isSqlQueryNode(values.nodeAttributes)) ||
                        props.nodeType === NotebookNodeType.DuckSQL) &&
                    __init.showSettings
                ) {
                    actions.updateAttributes({ showSettings: true })
                }
                props.updateAttributes({ __init: null })
            }
            if (
                props.nodeType === NotebookNodeType.Python ||
                (props.nodeType === NotebookNodeType.Query && isSqlQueryNode(values.nodeAttributes)) ||
                props.nodeType === NotebookNodeType.DuckSQL
            ) {
                const shouldShowSettings = __init?.showSettings ?? values.nodeAttributes.showSettings
                if (typeof shouldShowSettings === 'boolean') {
                    props.notebookLogic.actions.setEditingNodeEditing(values.nodeId, shouldShowSettings)
                }
            }
            if (props.nodeType === NotebookNodeType.DuckSQL) {
                const currentReturnVariable =
                    typeof values.nodeAttributes.returnVariable === 'string'
                        ? values.nodeAttributes.returnVariable
                        : 'duck_df'
                const uniqueReturnVariable = getUniqueDuckSqlReturnVariable(
                    values.duckSqlNodeSummaries,
                    values.nodeId,
                    currentReturnVariable
                )
                if (uniqueReturnVariable !== resolveDuckSqlReturnVariable(currentReturnVariable)) {
                    actions.updateAttributes({ returnVariable: uniqueReturnVariable })
                }
                const cachedExecution = values.nodeAttributes.duckExecution
                if (
                    !values.dataframeVariableName &&
                    cachedExecution?.status === 'ok' &&
                    typeof cachedExecution.result === 'string'
                ) {
                    const previewResult = parseDataframePreview(cachedExecution.result)
                    if (previewResult) {
                        actions.setDataframeVariableName(values.duckSqlReturnVariable, previewResult)
                    }
                }
            }
        },

        copyToClipboard: async () => {
            const { nodeAttributes } = values

            const htmlAttributesString = Object.entries(nodeAttributes)
                .map(([key, value]) => {
                    if (key === 'nodeId' || key.startsWith('__')) {
                        return ''
                    }

                    if (value === null || value === undefined) {
                        return ''
                    }

                    if (key === 'title') {
                        return `title='${JSON.stringify(value)}'`
                    }

                    return `${key}='${btoa(JSON.stringify(value))}'`
                })
                .filter((x) => !!x)
                .join(' ')

            const html = `<${props.nodeType} ${htmlAttributesString} data-pm-slice="0 0 []"></${props.nodeType}>`

            const type = 'text/html'
            const blob = new Blob([html], { type })
            const data = [new ClipboardItem({ [type]: blob })]

            await window.navigator.clipboard.write(data)
        },
        convertToBacklink: ({ href }) => {
            const pos = props.getPos?.()
            const editor = values.notebookLogic.values.editor
            if (!pos || !editor) {
                return
            }

            editor.insertContentAfterNode(pos, {
                type: NotebookNodeType.Backlink,
                attrs: {
                    href,
                },
            })
            actions.deleteNode()
        },
        runPythonNode: async ({ code }) => {
            if (props.nodeType !== NotebookNodeType.Python) {
                return
            }
            const notebook = values.notebook
            if (!notebook) {
                return
            }
            const executionSandboxId =
                values.kernelInfo?.sandbox_id ??
                (values.nodeAttributes as { pythonExecutionSandboxId?: string | null }).pythonExecutionSandboxId ??
                null
            const { executed, execution } = await runPythonCell({
                notebookId: notebook.short_id,
                code,
                exportedGlobals: values.exportedGlobals,
                updateAttributes: actions.updateAttributes,
                setPythonRunLoading: actions.setPythonRunLoading,
                executionSandboxId,
            })
            if (!executed) {
                actions.setDataframeVariableName(null)
                return
            }
            const dataframeVariable = findDataframeVariable(execution?.variables)
            actions.setDataframeVariableName(dataframeVariable)
        },

        runDuckSqlNode: async () => {
            if (props.nodeType !== NotebookNodeType.DuckSQL) {
                return
            }
            const notebook = values.notebook
            if (!notebook) {
                return
            }
            const { code = '', returnVariable = 'duck_df' } = values.nodeAttributes as {
                code?: string
                returnVariable?: string
                duckExecutionSandboxId?: string | null
            }
            const executionSandboxId =
                values.kernelInfo?.sandbox_id ?? values.nodeAttributes.duckExecutionSandboxId ?? null
            const resolvedReturnVariable = getUniqueDuckSqlReturnVariable(
                values.duckSqlNodeSummaries,
                values.nodeId,
                returnVariable
            )
            const { executed, execution } = await runDuckSqlCell({
                notebookId: notebook.short_id,
                code,
                returnVariable: resolvedReturnVariable,
                pageSize: values.dataframePageSize,
                updateAttributes: actions.updateAttributes,
                setDuckSqlRunLoading: actions.setDuckSqlRunLoading,
                executionSandboxId,
            })
            if (!executed || execution?.status !== 'ok') {
                actions.setDataframeVariableName(null)
                return
            }
            const previewResult = parseDataframePreview(execution?.result)
            actions.setDataframeVariableName(values.duckSqlReturnVariable, previewResult)
        },
        runDuckSqlNodeWithMode: async ({ mode }) => {
            if (props.nodeType !== NotebookNodeType.DuckSQL) {
                return
            }
            const notebook = values.notebook
            if (!notebook) {
                return
            }

            if (mode === 'cell') {
                await actions.runDuckSqlNode()
                return
            }

            const direction: DependencyRunDirection = mode === 'cell_downstream' ? 'downstream' : 'upstream'
            const nodesToRunWithLogic = getDependencyEntriesWithLogic({
                dependencyGraph: values.dependencyGraph,
                nodeId: values.nodeId,
                direction,
                notebookLogic: values.notebookLogic,
            })
            if (nodesToRunWithLogic.length === 0) {
                await actions.runDuckSqlNode()
                return
            }

            await runDependencyNodes({
                entries: nodesToRunWithLogic,
                notebookId: notebook.short_id,
                mode,
                duckSqlNodeSummaries: values.duckSqlNodeSummaries,
                currentNodeId: values.nodeId,
            })
        },

        runPythonNodeWithMode: async ({ mode }) => {
            if (props.nodeType !== NotebookNodeType.Python) {
                return
            }
            const notebook = values.notebook
            if (!notebook) {
                return
            }

            if (mode === 'cell') {
                await actions.runPythonNode({ code: (values.nodeAttributes as { code?: string }).code ?? '' })
                return
            }

            const direction: DependencyRunDirection = mode === 'cell_downstream' ? 'downstream' : 'upstream'
            const nodesToRunWithLogic = getDependencyEntriesWithLogic({
                dependencyGraph: values.dependencyGraph,
                nodeId: values.nodeId,
                direction,
                notebookLogic: values.notebookLogic,
            })
            if (nodesToRunWithLogic.length === 0) {
                await actions.runPythonNode({ code: (values.nodeAttributes as { code?: string }).code ?? '' })
                return
            }

            await runDependencyNodes({
                entries: nodesToRunWithLogic,
                notebookId: notebook.short_id,
                mode,
                duckSqlNodeSummaries: values.duckSqlNodeSummaries,
                currentNodeId: values.nodeId,
            })
        },
        setDataframeVariableName: ({ variableName, initialResult }) => {
            actions.resetDataframeResults()
            if (variableName) {
                if (initialResult) {
                    actions.setDataframeResult(initialResult)
                } else {
                    actions.loadDataframePage({ variableName })
                }
            }
        },
        setDataframePage: () => {
            if (!values.dataframeVariableName) {
                return
            }
            actions.loadDataframePage({ variableName: values.dataframeVariableName })
        },
        setDataframePageSize: ({ pageSize }) => {
            if (!values.dataframeVariableName) {
                return
            }
            actions.loadDataframePage({ variableName: values.dataframeVariableName, pageSize })
        },
        loadDataframePage: async ({ variableName, pageSize }) => {
            const notebook = values.notebook
            if (!notebook) {
                return
            }
            const nodeLogic = values.notebookLogic.values.findNodeLogicById(values.nodeId)
            if (
                props.nodeType === NotebookNodeType.DuckSQL &&
                nodeLogic &&
                !isDuckSqlExecutionFresh(
                    nodeLogic,
                    (values.nodeAttributes as { code?: string }).code ?? '',
                    values.duckSqlReturnVariable
                )
            ) {
                const nodesToRunWithLogic = getDependencyEntriesWithLogic({
                    dependencyGraph: values.dependencyGraph,
                    nodeId: values.nodeId,
                    direction: 'upstream',
                    notebookLogic: values.notebookLogic,
                })
                if (nodesToRunWithLogic.length > 0) {
                    await runDependencyNodes({
                        entries: nodesToRunWithLogic,
                        notebookId: notebook.short_id,
                        mode: 'cell_upstream',
                        duckSqlNodeSummaries: values.duckSqlNodeSummaries,
                        currentNodeId: values.nodeId,
                        skipDataframeVariableUpdateForNodeId: values.nodeId,
                    })
                }
            }
            actions.setDataframeLoading(true)
            actions.setDataframeError(null)
            const resolvedPageSize = pageSize ?? values.dataframePageSize
            const offset = (values.dataframePage - 1) * resolvedPageSize
            try {
                const response = await api.notebooks.kernelDataframe(notebook.short_id, {
                    variable_name: variableName,
                    offset,
                    limit: resolvedPageSize,
                })
                actions.setDataframeResult(response)
            } catch (error) {
                const message = error instanceof Error ? error.message : 'Failed to load dataframe results.'
                actions.setDataframeError(message)
                actions.setDataframeResult(null)
            } finally {
                actions.setDataframeLoading(false)
            }
        },
    })),

    afterMount((logic) => {
        const { props, actions, values } = logic

        // The node logic is mounted after the editor is mounted, so we need to wait a tick before we can register it
        queueMicrotask(() => {
            props.notebookLogic.actions.registerNodeLogic(values.nodeId, logic as any)
        })

        const isResizeable =
            typeof props.resizeable === 'function' ? props.resizeable(props.attributes) : (props.resizeable ?? true)

        actions.setResizeable(isResizeable)
        actions.initializeNode()
    }),

    beforeUnmount(({ props, values }) => {
        // Note this doesn't work as there may be other places where this is used. The NodeWrapper should be in charge of somehow unmounting this
        props.notebookLogic.actions.unregisterNodeLogic(values.nodeId)
    }),
])
