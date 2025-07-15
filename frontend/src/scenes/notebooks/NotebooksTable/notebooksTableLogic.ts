import { PaginationManual, Sorting } from '@posthog/lemon-ui'
import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api, { CountedPaginatedResponse } from 'lib/api'
import { objectClean, objectsEqual } from 'lib/utils'

import { notebooksModel } from '~/models/notebooksModel'
import { NotebookListItemType, NotebookNodeType } from '~/types'

import type { notebooksTableLogicType } from './notebooksTableLogicType'

export interface NotebooksListFilters {
    search: string
    // UUID of the user that created the notebook
    createdBy: string | null
    contains: NotebookNodeType[]
}

export const DEFAULT_FILTERS: NotebooksListFilters = {
    search: '',
    createdBy: null,
    contains: [],
}

const RESULTS_PER_PAGE = 50
const DEFAULT_SORTING: Sorting = { columnKey: '-created_at', order: 1 }

export const notebooksTableLogic = kea<notebooksTableLogicType>([
    path(['scenes', 'notebooks', 'NotebooksTable', 'notebooksTableLogic']),
    actions({
        loadNotebooks: true,
        setFilters: (filters: Partial<NotebooksListFilters>) => ({ filters }),
        tableSortingChanged: (sorting: Sorting | null) => ({
            sorting,
        }),
        setPage: (page: number) => ({ page }),
    }),
    connect(() => ({
        values: [notebooksModel, ['notebookTemplates']],
        actions: [notebooksModel, ['deleteNotebookSuccess']],
    })),
    reducers({
        filters: [
            DEFAULT_FILTERS,
            {
                setFilters: (state, { filters }) =>
                    objectClean({
                        ...state,
                        ...filters,
                    }),
            },
        ],
        sortValue: [
            null as string | null,
            {
                setSortValue: (_, { sortValue }) => sortValue,
            },
        ],
        page: [
            1,
            {
                setPage: (_, { page }) => page,
                setFilters: () => 1,
                setSortValue: () => 1,
            },
        ],
        tableSorting: [
            DEFAULT_SORTING,
            { persist: true },
            {
                tableSortingChanged: (_, { sorting }) => sorting || DEFAULT_SORTING,
            },
        ],
    }),
    loaders(({ values }) => ({
        notebooksResponse: [
            null as CountedPaginatedResponse<NotebookListItemType> | null,
            {
                loadNotebooks: async (_, breakpoint) => {
                    // TODO: Support pagination
                    await breakpoint(100)

                    const contains = values.filters?.contains.map((type) => ({ type, attrs: {} })) || undefined

                    const createdByForQuery =
                        values.filters?.createdBy === DEFAULT_FILTERS.createdBy ? undefined : values.filters?.createdBy

                    const res = await api.notebooks.list({
                        contains,
                        created_by: createdByForQuery ?? undefined,
                        search: values.filters?.search || undefined,
                        order: values.sortValue ?? '-last_modified_at',
                        limit: RESULTS_PER_PAGE,
                        offset: (values.page - 1) * RESULTS_PER_PAGE,
                    })

                    breakpoint()
                    return res
                },
            },
        ],
    })),
    listeners(({ actions }) => ({
        setFilters: () => actions.loadNotebooks(),
        setSortValue: () => actions.loadNotebooks(),
        setPage: () => actions.loadNotebooks(),
        deleteNotebookSuccess: () => actions.loadNotebooks(),
    })),
    selectors(({ actions }) => ({
        notebooksAndTemplates: [
            (s) => [s.notebooks, s.notebookTemplates, s.filters],
            (notebooks, notebookTemplates, filters): NotebookListItemType[] => {
                const includeTemplates = objectsEqual(filters, DEFAULT_FILTERS)
                return [...(includeTemplates ? (notebookTemplates as NotebookListItemType[]) : []), ...notebooks]
            },
        ],

        notebooks: [
            (s) => [s.notebooksResponse],
            (notebooksResponse): NotebookListItemType[] => {
                return notebooksResponse?.results || []
            },
        ],

        pagination: [
            (s) => [s.page, s.notebooksResponse],
            (page, notebooksResponse): PaginationManual => {
                return {
                    controlled: true,
                    pageSize: RESULTS_PER_PAGE,
                    currentPage: page,
                    entryCount: notebooksResponse?.count ?? 0,
                    onBackward: () => actions.setPage(page - 1),
                    onForward: () => actions.setPage(page + 1),
                }
            },
        ],
    })),
])
