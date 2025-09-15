import { actions, afterMount, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { router } from 'kea-router'
import { v4 as uuidv4 } from 'uuid'

import { DataTableNode } from '~/queries/schema/schema-general'

import type { dataTableSavedFiltersLogicType } from './dataTableSavedFiltersLogicType'

export interface DataTableSavedFilter {
    id: string
    name: string
    query: DataTableNode
    createdAt: string
    lastModifiedAt: string
}

export interface DataTableSavedFiltersLogicProps {
    uniqueKey: string
    query: DataTableNode
    setQuery: (query: DataTableNode) => void
}

const getStorageKey = (uniqueKey: string): string => `datatable-saved-filters-${uniqueKey}`

export const dataTableSavedFiltersLogic = kea<dataTableSavedFiltersLogicType>([
    props({} as DataTableSavedFiltersLogicProps),
    key((props) => props.uniqueKey),
    path(['queries', 'nodes', 'DataTable', 'dataTableSavedFiltersLogic']),

    actions({
        createSavedFilter: (name: string) => ({ name }),
        updateSavedFilter: (id: string, updates: Partial<DataTableSavedFilter>) => ({ id, updates }),
        deleteSavedFilter: (id: string) => ({ id }),
        applySavedFilter: (filter: DataTableSavedFilter) => ({ filter }),
        setAppliedSavedFilter: (filter: DataTableSavedFilter | null) => ({ filter }),
        setShowSavedFilters: (show: boolean) => ({ show }),
        loadSavedFilterFromUrl: true,
        updateUrlWithSavedFilter: (filterId: string | null) => ({ filterId }),
    }),

    reducers(({ props }) => ({
        savedFilters: [
            [] as DataTableSavedFilter[],
            {
                persist: true,
                storageKey: getStorageKey(props.uniqueKey),
            },
            {
                createSavedFilter: (state, { name }) => {
                    const newFilter: DataTableSavedFilter = {
                        id: uuidv4(),
                        name,
                        query: props.query,
                        createdAt: new Date().toISOString(),
                        lastModifiedAt: new Date().toISOString(),
                    }
                    return [...state, newFilter]
                },
                updateSavedFilter: (state, { id, updates }) => {
                    return state.map((filter) =>
                        filter.id === id
                            ? {
                                  ...filter,
                                  ...updates,
                                  lastModifiedAt: new Date().toISOString(),
                              }
                            : filter
                    )
                },
                deleteSavedFilter: (state, { id }) => state.filter((filter) => filter.id !== id),
            },
        ],

        appliedSavedFilter: [
            null as DataTableSavedFilter | null,
            {
                setAppliedSavedFilter: (_, { filter }) => filter,
            },
        ],

        showSavedFilters: [
            false,
            {
                setShowSavedFilters: (_, { show }) => show,
            },
        ],
    })),

    listeners(({ props, actions, values }) => ({
        applySavedFilter: ({ filter }) => {
            props.setQuery(filter.query)
            actions.setAppliedSavedFilter(filter)
            actions.updateUrlWithSavedFilter(filter.id)
        },

        createSavedFilter: () => {
            // Get the filter that was just created by the reducer
            // It will be the last one in the array since we append new filters
            const createdFilter = values.savedFilters[values.savedFilters.length - 1]

            if (createdFilter) {
                actions.setAppliedSavedFilter(createdFilter)
                actions.updateUrlWithSavedFilter(createdFilter.id)
            }
        },

        updateUrlWithSavedFilter: ({ filterId }) => {
            if (filterId) {
                router.actions.push(router.values.location.pathname, {
                    ...router.values.searchParams,
                    saved_filter_id: filterId,
                })
            } else {
                const { saved_filter_id, ...restParams } = router.values.searchParams
                router.actions.push(router.values.location.pathname, restParams)
            }
        },

        loadSavedFilterFromUrl: () => {
            const savedFilterId = router.values.searchParams.saved_filter_id

            if (savedFilterId) {
                const matchingFilter = values.savedFilters.find((filter) => filter.id === savedFilterId)

                if (matchingFilter) {
                    props.setQuery(matchingFilter.query)
                    actions.setAppliedSavedFilter(matchingFilter)
                } else {
                    // Remove invalid saved_filter_id from URL
                    actions.updateUrlWithSavedFilter(null)
                }
            }
        },

        deleteSavedFilter: ({ id }) => {
            // If we're deleting the currently applied filter, clear it from URL
            if (values.appliedSavedFilter?.id === id) {
                actions.updateUrlWithSavedFilter(null)
            }
        },
    })),

    selectors(() => ({
        hasUnsavedFilterChanges: [
            (s) => [s.appliedSavedFilter, (_, props) => props.query],
            (appliedSavedFilter, currentQuery): boolean => {
                if (!appliedSavedFilter) {
                    return false
                }
                return JSON.stringify(appliedSavedFilter.query) !== JSON.stringify(currentQuery)
            },
        ],
    })),

    afterMount(({ actions }) => {
        actions.loadSavedFilterFromUrl()
    }),
])
