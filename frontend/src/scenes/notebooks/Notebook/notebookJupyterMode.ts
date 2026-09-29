import { getNotebookStringProp } from 'lib/components/MarkdownNotebook/documentModel'
import type { MarkdownNotebookJupyterModeConfig } from 'lib/components/MarkdownNotebook/jupyterMode'
import type { NotebookComponentBlockNode } from 'lib/components/MarkdownNotebook/types'
import { uuid } from 'lib/utils/dom'

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

export function getNotebookJupyterModeConfig(onRestartKernel: () => void): MarkdownNotebookJupyterModeConfig {
    return {
        cellTagNames: NOTEBOOK_JUPYTER_CELL_TAG_NAMES,
        newCellTagName: 'PythonV2',
        getCellSource: (node) => getNotebookStringProp(node.props.code) ?? '',
        prepareCellCopy: prepareNotebookJupyterCellCopy,
        onRestartKernel,
    }
}
