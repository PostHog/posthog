import { actions, kea, path, reducers } from 'kea'

import { loaders } from 'kea-loaders'
import { NotebookListItemType } from '~/types'

import type { notebooksListLogicType } from './notebooksListLogicType'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import api from 'lib/api'

export const SCRATCHPAD_NOTEBOOK: NotebookListItemType = {
    short_id: 'scratchpad',
    title: 'Scratchpad',
    created_at: '',
    created_by: null,
}

export const notebooksListLogic = kea<notebooksListLogicType>([
    path(['scenes', 'notebooks', 'Notebook', 'notebooksListLogic']),
    actions({
        setScratchpadNotebook: (notebook: NotebookListItemType) => ({ notebook }),
        createNotebook: (redirect = false) => ({ redirect }),
        receiveNotebookUpdate: (notebook: NotebookListItemType) => ({ notebook }),
        loadNotebooks: true,
    }),

    reducers({
        scratchpadNotebook: [
            SCRATCHPAD_NOTEBOOK as NotebookListItemType,
            {
                setScratchpadNotebook: (_, { notebook }) => notebook,
            },
        ],
    }),

    loaders(({ values }) => ({
        notebooks: [
            [] as NotebookListItemType[],
            {
                loadNotebooks: async (_, breakpoint) => {
                    // TODO: Support pagination
                    await breakpoint(100)
                    const res = await api.notebooks.list()
                    return res.results
                },
                createNotebook: async ({ redirect }, breakpoint) => {
                    await breakpoint(100)
                    const notebook = await api.notebooks.create()

                    if (redirect) {
                        router.actions.push(urls.notebookEdit(notebook.short_id))
                    }

                    return [notebook]
                },

                receiveNotebookUpdate: ({ notebook }) => {
                    return values.notebooks.filter((n) => n.short_id !== notebook.short_id).concat([notebook])
                },
            },
        ],
    })),
])
