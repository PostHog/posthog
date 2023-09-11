import { actions, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { NotebookListItemType, NotebookNodeResource } from '~/types'

import api from 'lib/api'

import type { notebookSelectButtonLogicType } from './notebookSelectButtonLogicType'

export interface NotebookSelectButtonLogicProps {
    resource?: NotebookNodeResource
    // allows callers (e.g. storybook) to control starting visibility of the popover
    visible?: boolean
}

export const notebookSelectButtonLogic = kea<notebookSelectButtonLogicType>([
    path((key) => ['scenes', 'session-recordings', 'NotebookSelectButton', 'multiNotebookSelectButtonLogic', key]),
    props({} as NotebookSelectButtonLogicProps),
    key((props) => JSON.stringify(props.resource || 'load')),
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
        setSearchQuery: async (_, breakpoint) => {
            await breakpoint(300)
            actions.loadAllNotebooks()
            actions.loadContainingNotebooks()
        },

        setShowPopover: async ({ visible }) => {
            if (visible) {
                actions.loadAllNotebooks()
                actions.loadContainingNotebooks()
            }
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
                        props.resource
                            ? [{ type: props.resource.type, attrs: { id: props.resource.attrs?.id } }]
                            : undefined,
                        undefined,
                        values.searchQuery ?? undefined
                    )
                    // TODO for simplicity we'll assume the results will fit into one page
                    return response.results
                },
            },
        ],
    })),
    selectors(() => ({
        notebooksLoading: [
            (s) => [s.allNotebooksLoading, s.containingNotebooksLoading],
            (allNotebooksLoading, containingNotebooksLoading) => allNotebooksLoading || containingNotebooksLoading,
        ],
    })),
])
