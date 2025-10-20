import { actions, afterMount, connect, kea, key, listeners, path, props, reducers } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'
import posthog from 'posthog-js'

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

const INITIAL_SORTING = [] as string[]
const INITIAL_GROUPS_FILTER = [] as GroupPropertyFilter[]

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
    actions(() => ({
        setQuery: (query: DataTableNode) => ({ query }),
        setQueryWasModified: (queryWasModified: boolean) => ({ queryWasModified }),
        setGroupFilters: (filters: GroupPropertyFilter[]) => ({ filters }),
    })),
    reducers(() => ({
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
                }) as DataTableNode,
            { setQuery: (_, { query }) => query },
        ],
        groupFilters: [
            INITIAL_GROUPS_FILTER,
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

            if (values.query.source.kind !== NodeKind.GroupsQuery) {
                return [router.values.location.pathname, searchParams, undefined, { replace: true }]
            }

            if (values.query.source.properties?.length) {
                searchParams[`properties_${props.groupTypeIndex}`] = JSON.stringify(values.query.source.properties)
            }

            if (values.query.source.select?.length) {
                searchParams[`select_${props.groupTypeIndex}`] = JSON.stringify(values.query.source.select)
            }

            if (values.query.source.orderBy?.length) {
                searchParams[`orderBy_${props.groupTypeIndex}`] = JSON.stringify(values.query.source.orderBy)
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

            const queryOverrides = {} as Record<string, Array<string> | object>
            const parseParam = (paramName: string): void => {
                const rawParam = searchParams[`${paramName}_${props.groupTypeIndex}`]
                if (!rawParam) {
                    return
                }

                try {
                    const parsedParam = JSON.parse(rawParam)
                    if (parsedParam) {
                        queryOverrides[paramName] = parsedParam
                    }
                } catch (error: any) {
                    posthog.captureException('Failed to parse query overrides from URL', error)
                }
            }

            parseParam('properties')
            parseParam('select')
            parseParam('orderBy')

            if (Object.keys(queryOverrides).length > 0) {
                actions.setQuery({
                    ...values.query,
                    source: {
                        ...values.query.source,
                        ...queryOverrides,
                    },
                })
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
