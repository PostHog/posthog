import { actions, kea, listeners, reducers, path, selectors, connect } from 'kea'
import { NotebookListItemType, NotebookNodeType } from '~/types'
import api from 'lib/api'
import { objectClean, objectsEqual } from 'lib/utils'
import { loaders } from 'kea-loaders'

import type { notebooksTableLogicType } from './notebooksTableLogicType'
import { notebooksListLogic } from 'scenes/notebooks/Notebook/notebooksListLogic'

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
        values: [notebooksListLogic, ['notebookTemplates']],
    }),
    reducers({
        filters: [
            DEFAULT_FILTERS as NotebooksListFilters,
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
