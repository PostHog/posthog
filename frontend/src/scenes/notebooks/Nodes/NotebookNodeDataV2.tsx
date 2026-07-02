import { useActions, useMountedLogic, useValues } from 'kea'
import { useMemo } from 'react'

import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'

import { NotebookNodeAttributeProperties, NotebookNodeProps, NotebookNodeType } from '../types'
import { NotebookDataframeTable } from './components/NotebookDataframeTable'
import { NotebookCodeSQLEditorSettings } from './components/NotebookSQLEditor'
import { notebookNodeDataV2Logic } from './notebookNodeDataV2Logic'
import { notebookNodeLogic } from './notebookNodeLogic'
import { NotebookDataframeResult } from './pythonExecution'

export type NotebookNodeDataV2Result = {
    columns: string[]
    row_count: number
    first_page: (string | number | null)[][]
}

export type NotebookNodeDataV2Attributes = {
    code: string
    runId?: string | null
    result?: NotebookNodeDataV2Result | null
}

const toDataframeResult = (result: NotebookNodeDataV2Result): NotebookDataframeResult => {
    const columns = result.columns ?? []
    const firstPage = result.first_page ?? []
    return {
        columns,
        rows: firstPage.map((row) => Object.fromEntries(columns.map((column, index) => [column, row[index] ?? null]))),
        // Page over what we actually have; the envelope only carries the first page.
        rowCount: firstPage.length,
    }
}

const Component = ({
    attributes,
    updateAttributes,
}: NotebookNodeProps<NotebookNodeDataV2Attributes>): JSX.Element | null => {
    const nodeLogic = useMountedLogic(notebookNodeLogic)
    const { nodeId, notebookLogic, expanded } = useValues(nodeLogic)
    const notebookShortId = notebookLogic.props.shortId

    const dataLogic = notebookNodeDataV2Logic({
        nodeId,
        notebookShortId,
        updateAttributes,
        runId: attributes.runId ?? null,
        hasResult: !!attributes.result,
    })
    const { isRunning, runError } = useValues(dataLogic)

    const result = attributes.result ?? null
    const dataframeResult = useMemo(() => (result ? toDataframeResult(result) : null), [result])

    if (!expanded) {
        return null
    }

    return (
        <div data-attr="notebook-node-data-v2" className="flex h-full flex-col">
            <div
                className="space-y-3"
                onMouseDown={(event) => event.stopPropagation()}
                onDragStart={(event) => event.stopPropagation()}
            >
                {runError ? (
                    <div className="p-2 text-xs font-mono text-danger whitespace-pre-wrap">{runError}</div>
                ) : dataframeResult ? (
                    <NotebookDataframeTable
                        result={dataframeResult}
                        loading={isRunning}
                        page={1}
                        pageSize={Math.max(dataframeResult.rows.length, 1)}
                        onNextPage={() => {}}
                        onPreviousPage={() => {}}
                        onPageSizeChange={() => {}}
                    />
                ) : (
                    <div className="text-xs text-muted font-mono p-2">Run the query to see execution results.</div>
                )}
                {attributes.runId ? (
                    <div className="px-2 pb-2 text-[10px] uppercase tracking-wide text-muted select-text">
                        run_id: {attributes.runId}
                    </div>
                ) : null}
            </div>
        </div>
    )
}

const Settings = ({
    attributes,
    updateAttributes,
}: NotebookNodeAttributeProperties<NotebookNodeDataV2Attributes>): JSX.Element => {
    const nodeLogic = useMountedLogic(notebookNodeLogic)
    const { nodeId, notebookLogic } = useValues(nodeLogic)
    const notebookShortId = notebookLogic.props.shortId

    const dataLogic = notebookNodeDataV2Logic({
        nodeId,
        notebookShortId,
        updateAttributes,
        runId: attributes.runId ?? null,
        hasResult: !!attributes.result,
    })
    const { isRunning } = useValues(dataLogic)
    const { runQuery } = useActions(dataLogic)

    return (
        <NotebookCodeSQLEditorSettings
            attributes={attributes}
            updateAttributes={updateAttributes}
            tabIdSuffix="datav2"
            onRunQuery={() => runQuery(attributes.code ?? '')}
            runQueryLoading={isRunning}
            runQueryTooltip="Run Data (v2) query"
        />
    )
}

export const NotebookNodeDataV2 = createPostHogWidgetNode<NotebookNodeDataV2Attributes>({
    nodeType: NotebookNodeType.DataV2,
    titlePlaceholder: 'Data (v2)',
    Component,
    heightEstimate: 120,
    minHeight: 80,
    resizeable: true,
    startExpanded: true,
    attributes: {
        code: {
            default: '',
        },
        runId: {
            default: null,
        },
        result: {
            default: null,
        },
    },
    Settings,
    settingsPlacement: 'inline',
    serializedText: (attrs) => attrs.code,
})
