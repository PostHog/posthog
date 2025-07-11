import { actions, afterMount, connect, kea, key, listeners, path, props, reducers } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'
import { groupsAccessLogic } from 'lib/introductions/groupsAccessLogic'
import { teamLogic } from 'scenes/teamLogic'

import { groupsModel } from '~/models/groupsModel'
import { defaultDataTableColumns } from '~/queries/nodes/DataTable/utils'
import { NodeKind } from '~/queries/schema/schema-general'
import { DataTableNode } from '~/queries/schema/schema-general'
import { GroupPropertyFilter, GroupTypeIndex } from '~/types'

import type { groupsListLogicType } from './groupsListLogicType'

export interface GroupsListLogicProps {
    groupTypeIndex: GroupTypeIndex
}

const INITIAL_GROUPS_FILTER = [] as GroupPropertyFilter[]

export const groupsListLogic = kea<groupsListLogicType>([
    props({} as GroupsListLogicProps),
    key((props: GroupsListLogicProps) => props.groupTypeIndex),
    path(['groups', 'groupsListLogic']),
    connect(() => ({
        values: [
            teamLogic,
            ['currentTeamId'],
            groupsModel,
            ['groupTypes', 'aggregationLabel'],
            groupsAccessLogic,
            ['groupsEnabled'],
        ],
    })),
    actions(() => ({
        setQuery: (query: DataTableNode) => ({ query }),
        setQueryWasModified: (queryWasModified: boolean) => ({ queryWasModified }),
        setGroupFilters: (filters: GroupPropertyFilter[]) => ({ filters }),
    })),
    reducers(({ props }) => {
        const teamId = window.POSTHOG_APP_CONTEXT?.current_team?.id
        const persistConfig = { persist: true, prefix: `${teamId}__group_${props.groupTypeIndex}__` }

        return {
            query: [
                (_: any, props: GroupsListLogicProps) =>
                    ({
                        kind: NodeKind.DataTableNode,
                        source: {
                            kind: NodeKind.GroupsQuery,
                            select: undefined,
                            group_type_index: props.groupTypeIndex,
                        },
                        full: true,
                        showEventFilter: false,
                        showPersistentColumnConfigurator: true,
                        propertiesViaUrl: true,
                    } as DataTableNode),
                { setQuery: (_, { query }) => query },
            ],
            groupFilters: [
                INITIAL_GROUPS_FILTER,
                persistConfig,
                {
                    setGroupFilters: (_, { filters }) => filters,
                    setQuery: (state, { query }) => {
                        if (query.source.kind === NodeKind.GroupsQuery && query.source.properties) {
                            return query.source.properties
                        }
                        return state
                    },
                },
            ],
            queryWasModified: [
                false,
                {
                    setQueryWasModified: (_, { queryWasModified }) => queryWasModified,
                },
            ],
        }
    }),
    listeners(({ actions }) => ({
        setQuery: () => {
            actions.setQueryWasModified(true)
        },
    })),
    actionToUrl(({ values, props }) => ({
        setQuery: () => {
            if (router.values.location.pathname.includes(`/groups/${props.groupTypeIndex}`)) {
                const searchParams: Record<string, any> = {}

                if (values.query.source.kind === NodeKind.GroupsQuery && values.query.source.properties?.length) {
                    searchParams[`properties_${props.groupTypeIndex}`] = JSON.stringify(values.query.source.properties)
                }

                return [router.values.location.pathname, searchParams, undefined, { replace: true }]
            }
        },
    })),
    urlToAction(({ actions, values, props }) => ({
        [`/groups/${props.groupTypeIndex}`]: (_, searchParams) => {
            const properties = searchParams[`properties_${props.groupTypeIndex}`]
            if (properties && values.query.source.kind === NodeKind.GroupsQuery) {
                try {
                    const parsedProperties = JSON.parse(properties)
                    if (parsedProperties && Array.isArray(parsedProperties)) {
                        actions.setQuery({
                            ...values.query,
                            source: {
                                ...values.query.source,
                                properties: parsedProperties,
                            },
                        })
                    }
                } catch {}
            } else if (!properties && values.query.source.kind === NodeKind.GroupsQuery) {
                if (values.query.source.properties?.length) {
                    actions.setQuery({
                        ...values.query,
                        source: {
                            ...values.query.source,
                            properties: undefined,
                        },
                    })
                }
            }
        },
    })),
    afterMount(({ actions, values }) => {
        if (values.query.source.kind === NodeKind.GroupsQuery && values.query.source.select === undefined) {
            const defaultColumns = values.groupTypes.get(
                values.query.source.group_type_index as GroupTypeIndex
            )?.default_columns
            actions.setQuery({
                ...values.query,
                source: {
                    ...values.query.source,
                    select: defaultColumns ?? defaultDataTableColumns(NodeKind.GroupsQuery),
                },
            })
            actions.setQueryWasModified(false)
        }

        const shouldRestoreFiltersFromLocalStorage =
            values.query.source.kind === NodeKind.GroupsQuery &&
            !values.query.source.properties?.length &&
            values.groupFilters?.length
        if (shouldRestoreFiltersFromLocalStorage) {
            actions.setQuery({
                ...values.query,
                source: {
                    ...values.query.source,
                    properties: values.groupFilters,
                },
            })
        }
    }),
])
