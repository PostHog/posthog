import { actions, events, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { NotebookListItemType, NotebookNodeType } from '~/types'

import api from 'lib/api'

import type { notebookAddButtonLogicType } from './notebookAddButtonLogicType'

export interface NotebookAddButtonLogicProps {
    resource: {
        attrs: Record<string, any>
        type: NotebookNodeType
    }
    // allows callers (e.g. storybook) to control starting visibility of the popover
    visible?: boolean
}

export const notebookAddButtonLogic = kea<notebookAddButtonLogicType>([
    path((key) => ['scenes', 'session-recordings', 'NotebookAddButton', 'multiNotebookAddButtonLogic', key]),
    props({} as NotebookAddButtonLogicProps),
    key((props) => JSON.stringify(props.resource)),
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
            props.visible,
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
                        [{ type: props.resource.type, attrs: { id: props.resource.attrs?.id } }],
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
