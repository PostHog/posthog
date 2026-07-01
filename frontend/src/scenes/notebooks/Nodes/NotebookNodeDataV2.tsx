import { useActions, useMountedLogic, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'

import { NotebookNodeProps, NotebookNodeType } from '../types'
import { notebookNodeDataV2Logic } from './notebookNodeDataV2Logic'
import { notebookNodeLogic } from './notebookNodeLogic'

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

const renderResult = (result: NotebookNodeDataV2Result): string => {
    const isSingleCell = result.first_page.length === 1 && result.first_page[0]?.length === 1
    return isSingleCell ? String(result.first_page[0][0]) : `${result.row_count} rows`
}

const Component = ({
    attributes,
    updateAttributes,
}: NotebookNodeProps<NotebookNodeDataV2Attributes>): JSX.Element | null => {
    const nodeLogic = useMountedLogic(notebookNodeLogic)
    const { nodeId, notebookLogic } = useValues(nodeLogic)
    const notebookShortId = notebookLogic.props.shortId

    const dataLogic = notebookNodeDataV2Logic({ nodeId, notebookShortId, updateAttributes })
    const { isRunning, isStarting, runError } = useValues(dataLogic)
    const { runQuery, startInstance } = useActions(dataLogic)

    const result = attributes.result ?? null

    return (
        <div data-attr="notebook-node-data-v2" className="flex h-full flex-col gap-2 p-2">
            <textarea
                className="w-full rounded border border-border bg-bg-light p-2 font-mono text-xs text-default focus:outline-none focus:ring-1 focus:ring-primary"
                rows={3}
                value={attributes.code ?? ''}
                onChange={(event) => updateAttributes({ code: event.target.value })}
                placeholder="select count(*) from events where ..."
                spellCheck={false}
                onMouseDown={(event) => event.stopPropagation()}
            />
            <div className="flex items-center gap-2">
                <LemonButton
                    type="primary"
                    size="small"
                    loading={isRunning}
                    disabledReason={isRunning ? 'Running…' : undefined}
                    onClick={() => runQuery(attributes.code ?? '')}
                >
                    Run
                </LemonButton>
                <LemonButton
                    type="secondary"
                    size="small"
                    loading={isStarting}
                    disabledReason={isStarting ? 'Starting…' : undefined}
                    onClick={() => startInstance()}
                >
                    Start instance
                </LemonButton>
                <span className="text-[10px] uppercase tracking-wide text-muted">revamped-py-notebooks</span>
            </div>
            {runError ? (
                <div className="rounded border border-danger p-2 text-sm text-danger">{runError}</div>
            ) : result ? (
                <div className="rounded border border-border p-2 text-sm font-mono">{renderResult(result)}</div>
            ) : (
                <div className="text-xs text-muted">Run the query to see results.</div>
            )}
        </div>
    )
}

export const NotebookNodeDataV2 = createPostHogWidgetNode<NotebookNodeDataV2Attributes>({
    nodeType: NotebookNodeType.DataV2,
    titlePlaceholder: 'Data (v2)',
    Component,
    heightEstimate: 160,
    minHeight: 100,
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
    serializedText: (attrs) => attrs.code,
})
