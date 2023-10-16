import { actions, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { NotebookListItemType, NotebookNodeResource } from '~/types'

import api from 'lib/api'

import type { notebookSelectButtonLogicType } from './notebookSelectButtonLogicType'

export interface NotebookSelectButtonLogicProps {
    /**
     * Is a resource is provided it will be checke and added to the notebook when opened
     * If it is a boolean it simply determines how the popover is rendered
     *  */
    resource?: NotebookNodeResource | boolean
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
        loadNotebooksContainingResource: true,
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
            actions.loadNotebooksContainingResource()
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
        notebooksContainingResource: [
            [] as NotebookListItemType[],
            {
                loadNotebooksContainingResource: async (_, breakpoint) => {
                    breakpoint(100)
                    if (!props.resource) {
                        return []
                    }
                    const response = await api.notebooks.list(
                        props.resource && typeof props.resource !== 'boolean'
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
        notebooksNotContainingResource: [
            (s) => [s.allNotebooks, s.notebooksContainingResource],
            (allNotebooks, notebooksContainingResource) =>
                allNotebooks.filter(
                    (notebook) => !notebooksContainingResource.find((n) => n.short_id === notebook.short_id)
                ),
        ],
        notebooksLoading: [
            (s) => [s.allNotebooksLoading, s.notebooksContainingResourceLoading],
            (allNotebooksLoading, notebooksContainingResourceLoading) =>
                allNotebooksLoading || notebooksContainingResourceLoading,
        ],
    })),
])
