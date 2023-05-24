import { actions, kea, path, reducers } from 'kea'

import { loaders } from 'kea-loaders'
import { NotebookListItemType } from '~/types'

import type { notebooksListLogicType } from './notebooksListLogicType'
import { delay, uuid } from 'lib/utils'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'

const SCRATCHPAD_NOTEBOOK: NotebookListItemType = {
    short_id: 'scratchpad',
    title: 'Scratchpad',
    created_at: '',
    created_by: null,
}

const createLocalNotebook = (short_id: string): NotebookListItemType => ({
    short_id,
    created_at: '',
    created_by: null,
})

export const notebooksListLogic = kea<notebooksListLogicType>([
    path(['scenes', 'notebooks', 'Notebook', 'notebooksListLogic']),
    actions({
        setScratchpadNotebook: (notebook: NotebookListItemType) => ({ notebook }),
        createNotebook: (redirect = false) => ({ redirect }),
        receiveNotebookUpdate: (notebook: NotebookListItemType) => ({ notebook }),
    }),

    reducers({
        scratchpadNotebook: [
            SCRATCHPAD_NOTEBOOK as NotebookListItemType,
            {
                setScratchpadNotebook: (_, { notebook }) => notebook,
            },
        ],

        // NOTE: This is temporary, until we have a backend
        localNotebooks: [
            [] as NotebookListItemType[],
            { persist: true },
            {
                createNotebookSuccess: (_, { notebooks }) => notebooks,
                receiveNotebookUpdateSuccess: (_, { notebooks }) => notebooks,
            },
        ],
    }),

    loaders(({ values }) => ({
        notebooks: [
            [] as NotebookListItemType[],
            {
                loadNotebooks: async () => {
                    await delay(1000)
                    return values.localNotebooks
                },
                createNotebook: async ({ redirect }) => {
                    const notebook = createLocalNotebook(uuid())

                    await delay(1000)

                    if (redirect) {
                        setTimeout(() => {
                            // TODO: Remove this once we have proper DB backing
                            router.actions.push(urls.notebookEdit(notebook.short_id))
                        }, 500)
                    }

                    return [...values.localNotebooks, notebook]
                },

                receiveNotebookUpdate: ({ notebook }) => {
                    return values.localNotebooks.map((n) => (n.short_id === notebook.short_id ? notebook : n))
                },
            },
        ],
    })),
])
