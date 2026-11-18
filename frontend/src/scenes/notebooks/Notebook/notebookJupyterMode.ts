import { ApiConfig } from 'lib/api'
import { getNotebookStringProp } from 'lib/components/MarkdownNotebook/documentModel'
import type { MarkdownNotebookJupyterModeConfig } from 'lib/components/MarkdownNotebook/jupyterMode'
import type { NotebookComponentBlockNode } from 'lib/components/MarkdownNotebook/types'
import { uuid } from 'lib/utils/dom'

import { notebooksKernelCompleteCreate, notebooksKernelInspectCreate } from 'products/notebooks/frontend/generated/api'

export const NOTEBOOK_JUPYTER_CELL_TAG_NAMES = ['PythonV2', 'SQLV2']

const GENERATED_FRAME_NAME = /^(.*_)[0-9a-f]{8}$/

/**
 * A pasted cell keeps its code, but it needs a dataframe name of its own: two cells publishing the
 * same name would overwrite each other's frame for every later cell. Names the notebook generated
 * (`df_1a2b3c4d`) get a fresh suffix; a name the user typed is theirs to change.
 */
export function prepareNotebookJupyterCellCopy(node: NotebookComponentBlockNode): NotebookComponentBlockNode {
    const returnVariable = getNotebookStringProp(node.props.returnVariable)
    const match = returnVariable ? GENERATED_FRAME_NAME.exec(returnVariable) : null
    if (!match) {
        return node
    }
    return {
        ...node,
        props: { ...node.props, returnVariable: `${match[1]}${uuid().replace(/-/g, '').slice(-8)}` },
    }
}

/** New source makes the stored output wrong, so the cell drops it rather than show a stale result. */
export function withNotebookJupyterCellSource(
    node: NotebookComponentBlockNode,
    source: string
): NotebookComponentBlockNode {
    const { result: _result, runId: _runId, runStatus: _runStatus, ...props } = node.props
    return { ...node, props: { ...props, code: source } }
}

// Completion and inspection run in the Python kernel, so a SQL cell gets neither.
const isPythonCell = (node: NotebookComponentBlockNode): boolean => node.tagName === 'PythonV2'

export function getNotebookJupyterModeConfig(
    shortId: string,
    { onRestartKernel, onCommand }: Pick<MarkdownNotebookJupyterModeConfig, 'onRestartKernel' | 'onCommand'>
): MarkdownNotebookJupyterModeConfig {
    const projectId = (): string => String(ApiConfig.getCurrentTeamId())
    return {
        cellTagNames: NOTEBOOK_JUPYTER_CELL_TAG_NAMES,
        newCellTagName: 'PythonV2',
        getCellSource: (node) => getNotebookStringProp(node.props.code) ?? '',
        withCellSource: withNotebookJupyterCellSource,
        prepareCellCopy: prepareNotebookJupyterCellCopy,
        onRestartKernel,
        onCommand,
        completeCode: async (node, code, cursorPos) => {
            if (!isPythonCell(node)) {
                return null
            }
            try {
                const response = await notebooksKernelCompleteCreate(projectId(), shortId, {
                    code,
                    cursor_pos: cursorPos,
                })
                return {
                    matches: response.matches,
                    cursorStart: response.cursor_start,
                    cursorEnd: response.cursor_end,
                }
            } catch {
                // Completion is a convenience while typing: a failed lookup offers nothing, not an error.
                return null
            }
        },
        inspectCode: async (node, code, cursorPos) => {
            if (!isPythonCell(node)) {
                return null
            }
            try {
                const response = await notebooksKernelInspectCreate(projectId(), shortId, {
                    code,
                    cursor_pos: cursorPos,
                })
                return response.found ? response.text : null
            } catch {
                return null
            }
        },
    }
}
