import { actions, kea, reducers, path, listeners } from 'kea'
import { NodeType } from '../Nodes/types'
import { notebookLogic } from './notebookLogic'

import type { notebookSidebarLogicType } from './notebookSidebarLogicType'

export type NotebookType = {
    id: string
}

export const notebookSidebarLogic = kea<notebookSidebarLogicType>([
    path(['scenes', 'notebooks', 'Notebook', 'notebookSidebarLogic']),
    actions({
        setNotebookSideBarShown: (shown: boolean) => ({ shown }),
        setFullScreen: (full: boolean) => ({ full }),
        addNodeToNotebook: (type: NodeType, properties: Record<string, any>) => ({ type, properties }),
    }),
    reducers(() => ({
        notebooks: [
            [{ id: 'scratchpad' }] as NotebookType[],
            { persist: true },
            {
                createNotebook: (state, { id }) => [...state, { id }],
                deleteNotebook: (state, { id }) => state.filter((notebook) => notebook.id !== id),
                renameNotebook: (state, { id, name }) =>
                    state.map((notebook) => (notebook.id === id ? { ...notebook, name } : notebook)),
            },
        ],
        notebookId: [
            'scratchpad',
            { persist: true },
            {
                selectNotebook: (_, { id }) => id,
            },
        ],
        notebookSideBarShown: [
            false,
            { persist: true },
            {
                setNotebookSideBarShown: (_, { shown }) => shown,
                setFullScreen: () => true,
            },
        ],
        fullScreen: [
            false,
            {
                setFullScreen: (_, { full }) => full,
                setNotebookSideBarShown: (state, { shown }) => (!shown ? false : state),
            },
        ],
    })),

    listeners(({ values }) => ({
        addNodeToNotebook: ({ type, properties }) => {
            notebookLogic({ id: values.notebookId }).actions.addNodeToNotebook(type, properties)

            // if (!values.editor) {
            //     return
            // }
            // values.editor
            //     .chain()
            //     .focus()
            //     .insertContent({
            //         type,
            //         attrs: props,
            //     })
            //     .run()
        },
    })),
])
