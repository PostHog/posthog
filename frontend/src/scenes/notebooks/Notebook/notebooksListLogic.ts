import { actions, kea, path, reducers } from 'kea'

import { loaders } from 'kea-loaders'
import { NotebookListItemType } from '~/types'

import type { notebooksListLogicType } from './notebooksListLogicType'
import { uuid } from 'lib/utils'

const SCRATCHPAD_NOTEBOOK: NotebookListItemType = {
    id: 'scratchpad',
    short_id: 'scratchpad',
    title: 'Scratchpad',
    created_at: '',
    created_by: null,
}

const createLocalNotebook = (title: string): NotebookListItemType => ({
    id: title,
    short_id: title.toLowerCase().replace(/ /g, '-'),
    title,
    created_at: '',
    created_by: null,
})

export const notebooksListLogic = kea<notebooksListLogicType>([
    path(['scenes', 'notebooks', 'Notebook', 'notebooksListLogic']),
    actions({
        setScratchpadNotebook: (notebook: NotebookListItemType) => ({ notebook }),
        createNotebook: true,
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
                // deleteNotebook: (state, { id }) => state.filter((notebook) => notebook !== id),
            },
        ],
    }),

    loaders(({ values }) => ({
        notebooks: [
            [] as NotebookListItemType[],
            {
                loadNotebooks: () => {
                    return values.localNotebooks
                },
                createNotebook: () => {
                    const notebook = createLocalNotebook(uuid())

                    return [...values.localNotebooks, notebook]
                },
            },
        ],
    })),
])
