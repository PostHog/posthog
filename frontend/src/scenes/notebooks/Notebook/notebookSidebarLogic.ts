import { actions, kea, reducers, path, listeners, connect } from 'kea'
import { NotebookNodeType } from '../Nodes/types'
import { notebookLogic } from './notebookLogic'

import type { notebookSidebarLogicType } from './notebookSidebarLogicType'
import { urlToAction } from 'kea-router'
import { notebooksListLogic } from './notebooksListLogic'

export const notebookSidebarLogic = kea<notebookSidebarLogicType>([
    path(['scenes', 'notebooks', 'Notebook', 'notebookSidebarLogic']),
    actions({
        setNotebookSideBarShown: (shown: boolean) => ({ shown }),
        setFullScreen: (full: boolean) => ({ full }),
        addNodeToNotebook: (type: NotebookNodeType, properties: Record<string, any>) => ({ type, properties }),
        selectNotebook: (id: string) => ({ id }),
    }),

    connect({
        actions: [notebooksListLogic, ['createNotebookSuccess']],
    }),

    reducers(() => ({
        selectedNotebook: [
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

        createNotebookSuccess: ({ notebooks }) => {
            // NOTE: This is temporary: We probably only want to select it if it is created from the sidebar
            actions.selectNotebook(notebooks[notebooks.length - 1].id)
        },
    })),

    urlToAction(({ actions }) => ({
        '/*': () => {
            actions.setFullScreen(false)
        },
    })),
])
