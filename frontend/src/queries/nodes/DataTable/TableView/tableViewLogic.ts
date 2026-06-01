import equal from 'fast-deep-equal'
import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { lazyLoaders } from 'kea-loaders'
import posthog from 'posthog-js'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { getCurrentTeamId } from 'lib/utils/getAppContext'
import { GROUPS_LIST_DEFAULT_QUERY } from 'scenes/groups/groupsListLogic'
import { PERSON_EVENTS_CONTEXT_KEY } from 'scenes/persons/personsLogic'
import { PEOPLE_LIST_CONTEXT_KEY, PEOPLE_LIST_DEFAULT_QUERY } from 'scenes/persons/personsSceneLogic'
import { userLogic } from 'scenes/userLogic'

import { defaultDataTableColumns } from '~/queries/nodes/DataTable/utils'
import { ActorsQuery, EventsQuery, GroupsQuery, NodeKind } from '~/queries/schema/schema-general'
import { isEventsQuery } from '~/queries/utils'
import { AnyPropertyFilter, PropertyOperator } from '~/types'

import { ColumnConfigurationApi } from 'products/product_analytics/frontend/generated/api.schemas'

import type { tableViewLogicType } from './tableViewLogicType'

export type TableViewSupportedQueryType = ActorsQuery | GroupsQuery | EventsQuery

export interface TableViewLogicProps {
    contextKey: string
    query: TableViewSupportedQueryType
    setQuery: (query: TableViewSupportedQueryType) => void
}

interface EventSyntheticMarker {
    key: 'event'
    value: EventsQuery['event']
    operator: PropertyOperator.Exact
    type: undefined
}

interface EventsSyntheticMarker {
    key: 'events'
    value: EventsQuery['events']
    operator: PropertyOperator.In
    type: undefined
}

type TableViewSavedFilter = AnyPropertyFilter | EventSyntheticMarker | EventsSyntheticMarker

function getViewData(
    props: TableViewLogicProps,
    name?: string,
    visibility?: 'private' | 'shared'
): Partial<ColumnConfigurationApi> {
    if (!isEventsQuery(props.query)) {
        return {
            context_key: props.contextKey,
            ...(name && { name }),
            ...(visibility && { visibility }),
            columns: props.query.select,
            filters: props.query.properties,
        }
    }
    const event: EventSyntheticMarker = {
        key: 'event',
        value: props.query.event,
        operator: PropertyOperator.Exact,
        type: undefined,
    }
    const events: EventsSyntheticMarker = {
        key: 'events',
        value: props.query.events,
        operator: PropertyOperator.In,
        type: undefined,
    }
    return {
        context_key: props.contextKey,
        ...(name && { name }),
        ...(visibility && { visibility }),
        columns: props.query.select,
        filters: [...(props.query.properties || []), event, events],
    }
}

function isInitialPersonEventsQuery(query: TableViewSupportedQueryType): boolean {
    if (!isEventsQuery(query)) {
        return false
    }
    const defaultColumns = defaultDataTableColumns(NodeKind.EventsQuery)
    return equal(query.select, defaultColumns) && !query.properties?.length && !query.event && !query.events?.length
}

function getQueryFromView(
    query: TableViewSupportedQueryType,
    view: ColumnConfigurationApi
): TableViewSupportedQueryType {
    if (!isEventsQuery(query)) {
        return {
            ...query,
            select: view.columns || [],
            properties: view.filters || [],
        } as TableViewSupportedQueryType
    }

    const rawFilters = (view.filters || []) as TableViewSavedFilter[]
    const isEventMarker = (f: TableViewSavedFilter): f is EventSyntheticMarker =>
        f.key === 'event' && f.type === undefined
    const isEventsMarker = (f: TableViewSavedFilter): f is EventsSyntheticMarker =>
        f.key === 'events' && f.type === undefined
    const properties = rawFilters.filter((f): f is AnyPropertyFilter => !isEventMarker(f) && !isEventsMarker(f))
    const event = rawFilters.find(isEventMarker)?.value
    const events = rawFilters.find(isEventsMarker)?.value
    return {
        ...query,
        select: view.columns || [],
        properties,
        event,
        events,
    } as EventsQuery
}

export const tableViewLogic = kea<tableViewLogicType>([
    props({} as TableViewLogicProps),
    // Include the team id so a team switch yields a fresh logic instance
    // rather than reusing one whose storageKey is frozen to the old team.
    key((props) => `${getCurrentTeamId()}.${props.contextKey}`),
    path(['queries', 'nodes', 'DataTable', 'TableView', 'tableViewLogic']),
    connect({
        values: [userLogic, ['user']],
    }),

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
                    const response = await api.columnConfigurations.create({
                        data: getViewData(props, name, visibility),
                    })
                    return [...values.views, response]
                },

                updateView: async ({ id, updates }) => {
                    // If updating with current query state (no explicit updates provided)
                    if (!updates.name && !updates.visibility) {
                        updates = getViewData(props)
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

    reducers(({ props }) => ({
        currentView: [
            null as ColumnConfigurationApi | null,
            {
                persist: true,
                // Scope by team so views don't leak across projects (e.g. after impersonation).
                storageKey: `queries.nodes.DataTable.TableView.tableViewLogic.${getCurrentTeamId()}.${props.contextKey}.currentView`,
            },
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
    })),

    selectors(() => ({
        hasUnsavedChanges: [
            (s) => [s.currentView, (_, props) => props.query],
            (currentView, query): boolean => {
                if (!currentView) {
                    return false
                }
                const queryFromView = getQueryFromView(query, currentView)
                return !equal(queryFromView, query)
            },
        ],
        canEditCurrentView: [
            (s) => [s.currentView, s.user],
            (currentView, user): boolean => {
                if (!currentView || !user) {
                    return false
                }
                return currentView.created_by === user.id
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
                const response = await api.columnConfigurations.create({
                    data: getViewData(props, name, visibility),
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
            props.setQuery(getQueryFromView(props.query, view))
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

    afterMount(({ values, actions, props }) => {
        if (!values.currentView) {
            return
        }

        switch (props.contextKey) {
            case PEOPLE_LIST_CONTEXT_KEY:
                if (equal(props.query, PEOPLE_LIST_DEFAULT_QUERY.source)) {
                    actions.applyView(values.currentView)
                }
                break
            case 'group-0-list':
            case 'group-1-list':
            case 'group-2-list':
            case 'group-3-list':
            case 'group-4-list':
                const groupTypeIndex = parseInt(props.contextKey.split('-')[1])
                if (equal(props.query, GROUPS_LIST_DEFAULT_QUERY(groupTypeIndex).source)) {
                    actions.applyView(values.currentView)
                }
                break
            case PERSON_EVENTS_CONTEXT_KEY:
                if (isInitialPersonEventsQuery(props.query)) {
                    actions.applyView(values.currentView)
                }
                break
        }
    }),
])
