import { actions, afterMount, connect, kea, key, listeners, path, props, reducers } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'
import { groupsAccessLogic } from 'lib/introductions/groupsAccessLogic'
import { teamLogic } from 'scenes/teamLogic'

import { groupsModel } from '~/models/groupsModel'
import { defaultDataTableColumns } from '~/queries/nodes/DataTable/utils'
import { hogql } from '~/queries/utils'
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
                query: getGroupsSummaryQuery(props.groupTypeIndex, INITIAL_GROUPS_FILTER),
            }),
            {
                setGroupsSummaryQuery: (state, { query }) => ({
                    ...state,
                    query: query.query,
                }),
                setGroupFilters: (state, { filters }) => {
                    return {
                        ...state,
                        query: getGroupsSummaryQuery(props.groupTypeIndex, filters),
                    }
                },
                setQuery: (state, { query }) => {
                    if (query.source.kind === NodeKind.GroupsQuery && query.source.properties) {
                        return {
                            ...state,
                            query: getGroupsSummaryQuery(
                                props.groupTypeIndex,
                                query.source.properties as GroupPropertyFilter[]
                            ),
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
    listeners(({ actions }) => ({
        setQuery: () => {
            actions.setQueryWasModified(true)
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

function getGroupsSummaryQuery(groupTypeIndex: GroupTypeIndex, filters: GroupPropertyFilter[]): string {
    if (filters && filters.length > 0) {
        const propertyConditions = filters
            .map((filter) => {
                if ('key' in filter && 'value' in filter) {
                    const { key, value } = filter
                    const operator = 'operator' in filter ? filter.operator : 'exact'

                    if (operator === 'exact' || !operator) {
                        if (Array.isArray(value)) {
                            // Handle array values with IN operator
                            return hogql`JSONExtractString(properties, ${key}) IN ${value}`
                        }
                        // Handle single values
                        return hogql`JSONExtractString(properties, ${key}) = ${value}`
                    } else if (operator === 'icontains') {
                        if (Array.isArray(value)) {
                            // For array with icontains, check if any value matches
                            const conditions = value.map(
                                (v) => hogql`positionCaseInsensitive(JSONExtractString(properties, ${key}), ${v}) > 0`
                            )
                            return `(${conditions.join(' OR ')})`
                        }
                        return hogql`positionCaseInsensitive(JSONExtractString(properties, ${key}), ${value}) > 0`
                    } else if (operator === 'is_set') {
                        return hogql`JSONHas(properties, ${key})`
                    } else if (operator === 'is_not_set') {
                        return hogql`NOT JSONHas(properties, ${key})`
                    }
                }
                return null
            })
            .filter(Boolean)

        if (propertyConditions.length > 0) {
            return hogql`SELECT count() as group_count, sum(toFloatOrDefault(JSONExtractString(properties, 'mrr'), 0.0)) as mrr_sum FROM groups WHERE index = ${groupTypeIndex} AND ${hogql.raw(
                propertyConditions.join(' AND ')
            )}`
        }
    }

    return hogql`SELECT count() as group_count, sum(toFloatOrDefault(JSONExtractString(properties, 'mrr'), 0.0)) as mrr_sum FROM groups WHERE index = ${groupTypeIndex}`
}
