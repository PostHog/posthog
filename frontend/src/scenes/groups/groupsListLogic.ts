import { actions, afterMount, connect, kea, key, listeners, path, props, reducers } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'
import { groupsAccessLogic } from 'lib/introductions/groupsAccessLogic'
import { teamLogic } from 'scenes/teamLogic'

import { groupsModel } from '~/models/groupsModel'
import { defaultDataTableColumns } from '~/queries/nodes/DataTable/utils'
import { NodeKind } from '~/queries/schema/schema-general'
import { DataTableNode, HogQLQuery } from '~/queries/schema/schema-general'
import { GroupPropertyFilter, GroupTypeIndex } from '~/types'

import type { groupsListLogicType } from './groupsListLogicType'
import posthog from 'posthog-js'

export interface GroupsListLogicProps {
    groupTypeIndex: GroupTypeIndex
}

const INITIAL_SORTING = [] as string[]
const INITIAL_GROUPS_FILTER = [] as GroupPropertyFilter[]
const persistConfig = (groupTypeIndex: GroupTypeIndex): { persist: boolean; prefix: string } => ({
    persist: true,
    prefix: `${window.POSTHOG_APP_CONTEXT?.current_team?.id}__group_${groupTypeIndex}__`,
})

export const groupsListLogic = kea<groupsListLogicType>([
    props({} as GroupsListLogicProps),
    key((props: GroupsListLogicProps) => props.groupTypeIndex),
    path(['scenes', 'groups', 'groupsListLogic']),
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
    connect({
        values: [groupsModel, ['groupTypes', 'groupsTaxonomicTypes']],
    }),
    actions(() => ({
        setQuery: (query: DataTableNode) => ({ query }),
        setGroupsSummaryQuery: (query: HogQLQuery) => ({ query }),
        setQueryWasModified: (queryWasModified: boolean) => ({ queryWasModified }),
        setGroupFilters: (filters: GroupPropertyFilter[]) => ({ filters }),
    })),
    reducers(({ props }) => ({
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
        groupsSummaryQuery: [
            (_: any, props: GroupsListLogicProps) => ({
                kind: NodeKind.HogQLQuery,
                query: `SELECT count() as group_count, sum(toFloatOrDefault(JSONExtractString(properties, 'mrr'), 0.0)) as mrr_sum FROM groups WHERE index = ${props.groupTypeIndex}`,
                filters: {
                    properties: INITIAL_GROUPS_FILTER,
                },
            }),
            {
                setGroupsSummaryQuery: (state, { query }) => ({
                    ...state,
                    query: query.query,
                }),
                setGroupFilters: (state, { filters }) => {
                    return {
                        ...state,
                        filters: {
                            properties: filters,
                        },
                    }
                },
                setQuery: (state, { query }) => {
                    if (query.source.kind === NodeKind.GroupsQuery && query.source.properties) {
                        return {
                            ...state,
                            filters: {
                                properties: query.source.properties as GroupPropertyFilter[],
                            },
                        }
                    }
                    return state
                },
            },
        ],
        groupFilters: [
            INITIAL_GROUPS_FILTER,
            persistConfig(props.groupTypeIndex),
            {
                setGroupFilters: (_, { filters }) => filters,
                setQuery: (state, { query }) => {
                    if (query.source.kind === NodeKind.GroupsQuery && query.source.properties) {
                        return query.source.properties as GroupPropertyFilter[]
                    }
                    return state
                },
            },
        ],
        sorting: [
            INITIAL_SORTING,
            persistConfig(props.groupTypeIndex),
            {
                setQuery: (state, { query }) => {
                    if (query.source.kind === NodeKind.GroupsQuery && query.source.orderBy !== undefined) {
                        return query.source.orderBy
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
    })),
    listeners(({ actions, values }) => ({
        setQuery: () => {
            actions.setQueryWasModified(true)
        },
        setGroupFilters: ({ filters }) => {
            // Update the summary query when filters change
            if (values.query.source.kind === NodeKind.GroupsQuery) {
                actions.setGroupsSummaryQuery({
                    kind: NodeKind.HogQLQuery,
                    query: `SELECT count() as group_count, sum(toFloatOrDefault(JSONExtractString(properties, 'mrr'), 0.0)) as mrr_sum FROM groups WHERE index = ${values.query.source.group_type_index}`,
                    filters: {
                        properties: filters,
                    },
                })
            }
        },
    })),
    actionToUrl(({ values, props }) => ({
        setQuery: () => {
            const searchParams: Record<string, string> = {}

            if (values.query.source.kind === NodeKind.GroupsQuery && values.query.source.properties?.length) {
                searchParams[`properties_${props.groupTypeIndex}`] = JSON.stringify(values.query.source.properties)
            }

            return [router.values.location.pathname, searchParams, undefined, { replace: true }]
        },
        setGroupFilters: () => {
            const searchParams: Record<string, string> = {}

            if (values.groupFilters?.length) {
                searchParams[`properties_${props.groupTypeIndex}`] = JSON.stringify(values.groupFilters)
            }

            return [router.values.location.pathname, searchParams, undefined, { replace: true }]
        },
    })),
    urlToAction(({ actions, values, props }) => ({
        [`/groups/${props.groupTypeIndex}`]: (_, searchParams) => {
            if (values.query.source.kind !== NodeKind.GroupsQuery) {
                return
            }

            const properties = searchParams[`properties_${props.groupTypeIndex}`]
            if (properties) {
                try {
                    const parsedProperties = JSON.parse(properties)
                    if (parsedProperties && Array.isArray(parsedProperties)) {
                        actions.setQuery({
                            ...values.query,
                            source: {
                                ...values.query.source,
                                properties: parsedProperties,
                                orderBy: values.sorting,
                            },
                        })
                    }
                } catch (error: any) {
                    posthog.captureException('Failed to parse properties', error)
                }
            } else {
                actions.setQuery({
                    ...values.query,
                    source: {
                        ...values.query.source,
                        properties: values.groupFilters,
                        orderBy: values.sorting,
                    },
                })
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
    }),
])
