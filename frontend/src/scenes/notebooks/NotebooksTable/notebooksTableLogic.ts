import { actions, kea, listeners, reducers, path, selectors, connect } from 'kea'
import { NotebookListItemType, NotebookNodeType } from '~/types'
import api from 'lib/api'
import { objectClean, objectsEqual } from 'lib/utils'
import { loaders } from 'kea-loaders'

import type { notebooksTableLogicType } from './notebooksTableLogicType'
import { notebooksModel } from '~/models/notebooksModel'

export interface NotebooksListFilters {
    search: string
    // UUID of the user that created the notebook
    createdBy: string
    contains: NotebookNodeType[]
}

export const DEFAULT_FILTERS: NotebooksListFilters = {
    search: '',
    createdBy: 'All users',
    contains: [],
}

export const notebooksTableLogic = kea<notebooksTableLogicType>([
    path(['scenes', 'notebooks', 'NotebooksTable', 'notebooksTableLogic']),
    actions({
        loadNotebooks: true,
        setFilters: (filters: Partial<NotebooksListFilters>) => ({ filters }),
    }),
    connect({
        values: [notebooksModel, ['notebookTemplates']],
        actions: [notebooksModel, ['deleteNotebookSuccess']],
    }),
    reducers({
        filters: [
            DEFAULT_FILTERS,
            {
                setFilters: (state, { filters }) =>
                    objectClean({
                        ...(state || {}),
                        ...filters,
                    }),
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

                    const contains = values.filters?.contains.map((type) => ({ type, attrs: {} })) || undefined

                    const createdByForQuery =
                        values.filters?.createdBy === DEFAULT_FILTERS.createdBy ? undefined : values.filters?.createdBy

                    const res = await api.notebooks.list(contains, createdByForQuery, values.filters?.search)

                    breakpoint()
                    return res.results
                },
            },
        ],
    })),
    listeners(({ actions }) => ({
        setFilters: () => {
            actions.loadNotebooks()
        },
        deleteNotebookSuccess: () => {
            // TODO at some point this will be slow enough it makes sense to patch the in-memory list but for simplicity...
            actions.loadNotebooks()
        },
    })),
    selectors({
        notebooksAndTemplates: [
            (s) => [s.notebooks, s.notebookTemplates, s.filters],
            (notebooks, notebookTemplates, filters): NotebookListItemType[] => {
                const includeTemplates = objectsEqual(filters, DEFAULT_FILTERS)
                return [...(includeTemplates ? (notebookTemplates as NotebookListItemType[]) : []), ...notebooks]
            },
        ],
    }),
])
