import { actions, events, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { NotebookListItemType, NotebookNodeType } from '~/types'

import api from 'lib/api'

import type { notebookCommentButtonLogicType } from './notebookCommentButtonLogicType'

export interface NotebookCommentButtonProps {
    sessionRecordingId: string
    startVisible: boolean
}

export const notebookCommentButtonLogic = kea<notebookCommentButtonLogicType>([
    path((key) => ['scenes', 'session-recordings', 'NotebookCommentButton', 'multiNotebookCommentButtonLogic', key]),
    props({} as NotebookCommentButtonProps),
    key((props) => props.sessionRecordingId || 'no recording id yet'),
    actions({
        setShowPopover: (visible: boolean) => ({ visible }),
        setSearchQuery: (query: string) => ({ query }),
        loadContainingNotebooks: true,
        loadAllNotebooks: true,
    }),
    reducers(({ props }) => ({
        searchQuery: [
            '',
            {
                setSearchQuery: (_, { query }) => query,
            },
        ],
        showPopover: [
            props.startVisible,
            {
                setShowPopover: (_, { visible }) => visible,
            },
        ],
    })),
    listeners(({ actions }) => ({
        setSearchQuery: () => {
            actions.loadAllNotebooks()
            actions.loadContainingNotebooks()
        },
    })),
    loaders(({ props, values }) => ({
        allNotebooks: [
            [] as NotebookListItemType[],
            {
                loadAllNotebooks: async (_, breakpoint) => {
                    breakpoint(100)
                    const response = await api.notebooks.list(undefined, undefined, values.searchQuery ?? undefined)
                    // TODO for simplicity we'll assume the results will fit into one page
                    return response.results
                },
            },
        ],
        containingNotebooks: [
            [] as NotebookListItemType[],
            {
                loadContainingNotebooks: async (_, breakpoint) => {
                    breakpoint(100)
                    const response = await api.notebooks.list(
                        [{ type: NotebookNodeType.Recording, attrs: { id: props.sessionRecordingId } }],
                        undefined,
                        values.searchQuery ?? undefined
                    )
                    // TODO for simplicity we'll assume the results will fit into one page
                    return response.results
                },
            },
        ],
    })),
    events(({ actions }) => ({
        afterMount: () => {
            actions.loadAllNotebooks()
            actions.loadContainingNotebooks()
        },
    })),
    selectors(() => ({
        notebooksLoading: [
            (s) => [s.allNotebooksLoading, s.containingNotebooksLoading],
            (allNotebooksLoading, containingNotebooksLoading) => allNotebooksLoading || containingNotebooksLoading,
        ],
    })),
])
