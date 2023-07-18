import { kea, props, key, path } from 'kea'
import type { notebookNodeLogicType } from './notebookNodeLogicType'

export type NotebookNodeLogicProps = {
    nodeId: string
    notebookShortId?: string
    getPos?: () => number
}

export const notebookNodeLogic = kea<notebookNodeLogicType>([
    props({} as NotebookNodeLogicProps),
    path((key) => ['scenes', 'notebooks', 'Notebook', 'Nodes', 'notebookNodeLogic', key]),
    key(({ nodeId }) => nodeId),
])
