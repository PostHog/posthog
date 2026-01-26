import { actions, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { lazyLoaders } from 'kea-loaders'
import posthog from 'posthog-js'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { ActorsQuery, EventsQuery, GroupsQuery } from '~/queries/schema/schema-general'

import { ColumnConfigurationApi } from 'products/product_analytics/frontend/generated/api.schemas'

import type { tableViewLogicType } from './tableViewLogicType'

export type TableViewSupportedQueryType = ActorsQuery | GroupsQuery | EventsQuery

export interface TableViewLogicProps {
    contextKey: string
    query: TableViewSupportedQueryType
    setQuery: (query: TableViewSupportedQueryType) => void
}

export const tableViewLogic = kea<tableViewLogicType>([
    props({} as TableViewLogicProps),
    key((props) => props.contextKey),
    path(['queries', 'nodes', 'DataTable', 'TableView', 'tableViewLogic']),

    actions({
        loadViews: true,
        saveCurrentAsView: (name: string, visibility: 'private' | 'shared') => ({ name, visibility }),
        updateView: (id: string, updates: Partial<ColumnConfigurationApi>) => ({ id, updates }),
        deleteView: (id: string) => ({ id }),
        applyView: (view: ColumnConfigurationApi) => ({ view }),
        setCurrentView: (view: ColumnConfigurationApi | null) => ({ view }),
        setShowDeleteConfirm: (viewId: string | null) => ({ viewId }),
        setIsCreating: (isCreating: boolean) => ({ isCreating }),
    }),

    lazyLoaders(({ props, values }) => ({
        views: [
            [] as ColumnConfigurationApi[],
            {
                loadViews: async () => {
                    const response = await api.columnConfigurations.list({
                        context_key: props.contextKey,
                    })
                    return response.results
                },

                saveCurrentAsView: async ({ name, visibility }) => {
                    const viewData = {
                        context_key: props.contextKey,
                        name,
                        columns: props.query.select,
                        filters: props.query.properties,
                        visibility,
                    }

                    const response = await api.columnConfigurations.create({
                        data: viewData,
                    })
                    return [...values.views, response]
                },

                updateView: async ({ id, updates }) => {
                    // If updating with current query state (no explicit updates provided)
                    if (!updates.name && !updates.visibility) {
                        updates = {
                            columns: props.query.select || [],
                            filters: props.query.properties || [],
                        }
                    }

                    const response = await api.columnConfigurations.update({
                        id,
                        data: updates,
                    })

                    return values.views.map((v) => (v.id === id ? response : v))
                },

                deleteView: async ({ id }) => {
                    await api.columnConfigurations.delete({ id })
                    return values.views.filter((v) => v.id !== id)
                },
            },
        ],
    })),

    reducers({
        currentView: [
            null as ColumnConfigurationApi | null,
            { persist: true },
            {
                setCurrentView: (_, { view }) => view,
                applyView: (_, { view }) => view,
                loadViewsSuccess: (state, { views }) => {
                    if (views.length === 0) {
                        return null
                    }
                    if (!state) {
                        return views[0] || null
                    }
                    return state
                },
                deleteViewSuccess: (state, { views }) => {
                    if (state && !views.find((v) => v.id === state.id)) {
                        return null
                    }
                    return state
                },
            },
        ],
        showDeleteConfirm: [
            null as string | null,
            {
                setShowDeleteConfirm: (_, { viewId }) => viewId,
            },
        ],
        isCreating: [
            false,
            {
                setIsCreating: (_, { isCreating }) => isCreating,
                saveCurrentAsViewSuccess: () => false,
            },
        ],
    }),

    selectors(() => ({
        hasUnsavedChanges: [
            (s) => [s.currentView, (_, props) => props.query],
            (currentView, query): boolean => {
                if (!currentView) {
                    return false
                }
                // Compare current query state with saved view state
                const currentColumns = query.select || []
                const currentFilters = query.properties || []

                const columnsChanged = JSON.stringify(currentColumns) !== JSON.stringify(currentView.columns)
                const filtersChanged = JSON.stringify(currentFilters) !== JSON.stringify(currentView.filters)

                return columnsChanged || filtersChanged
            },
        ],
    })),

    forms(({ props, actions }) => ({
        newViewForm: {
            defaults: {
                name: '',
                visibility: 'private' as 'private' | 'shared',
            },
            errors: ({ name }) => ({
                name: !name?.trim() ? 'Name is required' : undefined,
            }),
            submit: async ({ name, visibility }) => {
                const viewData = {
                    context_key: props.contextKey,
                    name: name.trim(),
                    columns: props.query.select,
                    filters: props.query.properties,
                    visibility,
                }

                const response = await api.columnConfigurations.create({
                    data: viewData,
                })

                actions.loadViews()
                actions.applyView(response)
                actions.resetNewViewForm()
                actions.setIsCreating(false)
            },
        },
    })),

    listeners(({ props, actions, values }) => ({
        applyView: ({ view }) => {
            const newQuery = {
                ...props.query,
                select: view.columns || [],
                properties: view.filters || [],
            } as TableViewSupportedQueryType

            props.setQuery(newQuery)
        },

        saveCurrentAsViewSuccess: () => {
            actions.setIsCreating(false)
        },

        saveCurrentAsViewFailure: (error) => {
            posthog.captureException(error)
            lemonToast.error('Error saving view')
        },

        updateViewSuccess: ({ payload }) => {
            const updatedView = values.views.find((view) => view.id === payload?.id)
            if (updatedView) {
                actions.applyView(updatedView)
            }
            lemonToast.success(`View "${updatedView?.name || ''}" updated`)
        },

        updateViewFailure: (error) => {
            posthog.captureException(error)
            lemonToast.error('Error updating view')
        },

        deleteViewSuccess: () => {
            lemonToast.success('View deleted')
        },

        deleteViewFailure: (error) => {
            posthog.captureException(error)
            lemonToast.error('Error deleting view')
        },

        loadViewsFailure: (error) => {
            posthog.captureException(error)
            lemonToast.error('Error loading views')
        },

        submitNewViewFormSuccess: ({ newViewForm }) => {
            lemonToast.success(`View "${newViewForm.name}" saved`)
        },

        submitNewViewFormFailure: (error) => {
            posthog.captureException(error)
            lemonToast.error('Error creating view')
        },
    })),
])
