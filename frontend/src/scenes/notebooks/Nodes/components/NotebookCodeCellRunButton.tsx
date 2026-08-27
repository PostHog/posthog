import { useActions, useMountedLogic, useValues } from 'kea'
import { useCallback } from 'react'

import { IconPlayFilled } from '@posthog/icons'

import type { NotebookComponentToolbarProps } from 'lib/components/MarkdownNotebook/types'
import { getSerializableProps } from 'lib/components/MarkdownNotebook/utils'
import { IconCancel } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { sqlEditorLogic } from 'scenes/data-warehouse/editor/sqlEditorLogic'

import { notebookLogic } from '../../Notebook/notebookLogic'
import {
    type NotebookNodeSQLV2LogicProps,
    type RunNodeOverrides,
    notebookNodeSQLV2Logic,
} from '../notebookNodeSQLV2Logic'
import { getNotebookSqlEditorTabId } from './NotebookSQLEditor'

/**
 * Run/Cancel for a revamped code cell (SQL or Python), rendered in the block's top row.
 *
 * It sits in the shell toolbar rather than in the code editor so that reading a notebook is
 * enough to rerun a cell: in view mode there is no editor on screen, and in edit mode the
 * editor may be collapsed. The shell mounts this outside the panels, so the run state stays
 * live either way.
 */
export function NotebookCodeCellRunButton({ node, updateProps }: NotebookComponentToolbarProps): JSX.Element | null {
    const mountedNotebookLogic = useMountedLogic(notebookLogic)
    const { isShared, canEditNotebook } = useValues(mountedNotebookLogic)
    // Cells persist their own id; a parsed markdown block id is a content fingerprint that drifts
    // as soon as a run writes runId/result, so it is only the fallback for a never-run cell.
    const nodeId = typeof node.props.nodeId === 'string' && node.props.nodeId ? node.props.nodeId : node.id
    const updateAttributes = useCallback<NotebookNodeSQLV2LogicProps['updateAttributes']>(
        (attributes) => updateProps(getSerializableProps(attributes)),
        [updateProps]
    )

    const dataLogic = notebookNodeSQLV2Logic({
        nodeId,
        notebookShortId: mountedNotebookLogic.props.shortId,
        updateAttributes,
        runId: typeof node.props.runId === 'string' ? node.props.runId : null,
        hasResult: !!node.props.result,
        getContent: () => mountedNotebookLogic.values.content ?? null,
    })
    const { isRunning, isInterrupting, operationBlockReason } = useValues(dataLogic)
    const { runNode, interruptRun } = useActions(dataLogic)

    // The run endpoint requires editor access on the notebook, so it is offered only to a reader it
    // will answer for. That excludes a public share, a viewer-level reader, and a history preview,
    // all of which render this toolbar in view mode. Without the gate they get a control that
    // returns 403, and a preview would run a version of the code the reader is not editing.
    if (isShared || !canEditNotebook) {
        return null
    }

    const run = (): void => {
        // A SQL cell's editor holds the code and the connection a keystroke or a just-picked
        // connection before the document does, so prefer it while it is open. A Python cell has no
        // such logic mounted and runs from the document.
        const editorLogic = sqlEditorLogic.findMounted({ tabId: getNotebookSqlEditorTabId(nodeId, 'datav2') })
        const overrides: RunNodeOverrides = editorLogic
            ? {
                  // Pass every string the editor holds, blank included. An editor cleared a render
                  // ahead of the document holds `''`, which has to reach the blank-code check and
                  // be rejected. Dropping it here would fall back to the document and run the
                  // previous query instead. Only `null`, an editor that never took input, defers to
                  // the document.
                  code: editorLogic.values.queryInput ?? undefined,
                  connectionId: editorLogic.values.selectedConnectionId ?? null,
                  sendRawQuery: editorLogic.values.sendRawQueryEnabled,
              }
            : {}
        runNode(overrides)
    }

    return (
        <LemonButton
            data-attr="notebook-code-cell-run-button"
            size="xsmall"
            type="primary"
            icon={isRunning ? <IconCancel /> : <IconPlayFilled color="var(--success)" />}
            onClick={() => {
                if (!isRunning) {
                    run()
                } else if (!isInterrupting) {
                    // Guard against double submission: one interrupt request at a time.
                    interruptRun()
                }
            }}
            loading={isInterrupting}
            disabledReason={operationBlockReason ?? undefined}
            tooltip={isRunning ? 'Stop the running cell' : 'Run cell (⌘⏎)'}
        >
            {isRunning ? 'Cancel' : 'Run'}
        </LemonButton>
    )
}
