import { actions, kea, reducers, path, listeners } from 'kea'
import { NotebookNodeType } from '../Nodes/types'
import { notebookLogic } from './notebookLogic'

import type { notebookSidebarLogicType } from './notebookSidebarLogicType'
import { urlToAction } from 'kea-router'

export const notebookSidebarLogic = kea<notebookSidebarLogicType>([
    path(['scenes', 'notebooks', 'Notebook', 'notebookSidebarLogic']),
    actions({
        setNotebookSideBarShown: (shown: boolean) => ({ shown }),
        setFullScreen: (full: boolean) => ({ full }),
        addNodeToNotebook: (type: NotebookNodeType, properties: Record<string, any>) => ({ type, properties }),
        createNotebook: (id: string) => ({ id }),
        deleteNotebook: (id: string) => ({ id }),
        renameNotebook: (id: string, name: string) => ({ id, name }),
        selectNotebook: (id: string) => ({ id }),
    }),

    reducers(() => ({
        notebooks: [
            ['scratchpad', 'RFC: Notebooks', 'Feature Flag overview', 'HoqQL examples'] as string[],
            {
                createNotebook: (state, { id }) => [...state, id],
                deleteNotebook: (state, { id }) => state.filter((notebook) => notebook !== id),
            },
        ],
        selectedNotebook: [
            'scratchpad',
            { persist: true },
            {
                selectNotebook: (_, { id }) => id,
                createNotebook: (_, { id }) => id,
            },
        ],
        notebookSideBarShown: [
            false,
            { persist: true },
            {
                setNotebookSideBarShown: (_, { shown }) => shown,
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

    listeners(({ values, actions }) => ({
        addNodeToNotebook: ({ type, properties }) => {
            notebookLogic({ id: values.selectedNotebook }).actions.addNodeToNotebook(type, properties)

            actions.setNotebookSideBarShown(true)
        },
    })),

    urlToAction(({ actions }) => ({
        '/*': () => {
            actions.setFullScreen(false)
        },
    })),
])
