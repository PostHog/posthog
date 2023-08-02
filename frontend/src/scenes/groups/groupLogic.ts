import { kea } from 'kea'
import api from 'lib/api'
import { toParams } from 'lib/utils'
import { teamLogic } from 'scenes/teamLogic'
import { groupsModel } from '~/models/groupsModel'
import { Breadcrumb, Group, PropertyFilterType, PropertyOperator } from '~/types'
import type { groupLogicType } from './groupLogicType'
import { urls } from 'scenes/urls'
import { capitalizeFirstLetter } from 'lib/utils'
import { groupDisplayId } from 'scenes/persons/GroupActorDisplay'
import { DataTableNode, Node, NodeKind } from '~/queries/schema'
import { defaultDataTableColumns } from '~/queries/nodes/DataTable/utils'
import { isDataTableNode } from '~/queries/utils'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'

function getGroupEventsQuery(groupTypeIndex: number, groupKey: string): DataTableNode {
    return {
        kind: NodeKind.DataTableNode,
        full: true,
        source: {
            kind: NodeKind.EventsQuery,
            select: defaultDataTableColumns(NodeKind.EventsQuery),
            after: '-24h',
            fixedProperties: [
                {
                    key: `$group_${groupTypeIndex}`,
                    value: groupKey,
                    type: PropertyFilterType.Event,
                    operator: PropertyOperator.Exact,
                },
            ],
        },
    }
}

export const groupLogic = kea<groupLogicType>({
    path: ['groups', 'groupLogic'],
    connect: {
        values: [
            teamLogic,
            ['currentTeamId'],
            groupsModel,
            ['groupTypes', 'aggregationLabel'],
            featureFlagLogic,
            ['featureFlags'],
        ],
    },
    actions: () => ({
        setGroup: (groupTypeIndex: number, groupKey: string, groupTab?: string | null) => ({
            groupTypeIndex,
            groupKey,
            groupTab,
        }),
        setGroupTab: (groupTab: string | null) => ({ groupTab }),
        setGroupEventsQuery: (query: Node) => ({ query }),
    }),
    loaders: ({ values }) => ({
        groupData: [
            null as Group | null,
            {
                loadGroup: async () => {
                    const params = { group_type_index: values.groupTypeIndex, group_key: values.groupKey }
                    const url = `api/projects/${values.currentTeamId}/groups/find?${toParams(params)}`
                    return await api.get(url)
                },
            },
        ],
    }),
    reducers: {
        groupTypeIndex: [
            0,
            {
                setGroup: (_, { groupTypeIndex }) => groupTypeIndex,
            },
        ],
        groupKey: [
            '',
            {
                setGroup: (_, { groupKey }) => groupKey,
            },
        ],
        groupTab: [
            null as string | null,
            {
                setGroup: (_, { groupTab }) => groupTab ?? null,
                setGroupTab: (_, { groupTab }) => groupTab,
            },
        ],
        groupEventsQuery: [
            null as DataTableNode | null,
            {
                setGroup: (_, { groupTypeIndex, groupKey }) => getGroupEventsQuery(groupTypeIndex, groupKey),
                setGroupEventsQuery: (_, { query }) => (isDataTableNode(query) ? query : null),
            },
        ],
    },
    selectors: {
        showCustomerSuccessDashboards: [
            (s) => [s.featureFlags],
            (featureFlags) => featureFlags[FEATURE_FLAGS.CS_DASHBOARDS],
        ],
        groupTypeName: [
            (s) => [s.aggregationLabel, s.groupTypeIndex],
            (aggregationLabel, index): string => aggregationLabel(index).singular,
        ],
        groupType: [
            (s) => [s.groupTypes, s.groupTypeIndex],
            (groupTypes, index): string => groupTypes[index]?.group_type,
        ],
        breadcrumbs: [
            (s) => [s.groupTypeName, s.groupTypeIndex, s.groupKey, s.groupData],
            (groupTypeName, groupTypeIndex, groupKey, groupData): Breadcrumb[] => [
                {
                    name: capitalizeFirstLetter(groupTypeName),
                    path: urls.groups(String(groupTypeIndex)),
                },
                {
                    name: groupDisplayId(groupKey, groupData?.group_properties || {}),
                    path: urls.group(String(groupTypeIndex), groupKey),
                },
            ],
        ],
    },
    actionToUrl: ({ values }) => ({
        setGroup: () => {
            const { groupTypeIndex, groupKey, groupTab } = values
            return urls.group(String(groupTypeIndex), groupKey, true, groupTab)
        },
        setGroupTab: () => {
            const { groupTypeIndex, groupKey, groupTab } = values
            return urls.group(String(groupTypeIndex), groupKey, true, groupTab)
        },
    }),
    urlToAction: ({ actions, values }) => ({
        '/groups/:groupTypeIndex/:groupKey(/:groupTab)': ({ groupTypeIndex, groupKey, groupTab }) => {
            if (groupTypeIndex && groupKey) {
                if (+groupTypeIndex === values.groupTypeIndex && groupKey === values.groupKey) {
                    actions.setGroupTab(groupTab || null)
                } else {
                    actions.setGroup(+groupTypeIndex, decodeURIComponent(groupKey), groupTab)
                }
            }
        },
    }),
    listeners: ({ actions, selectors, values }) => ({
        setGroup: (_, __, ___, previousState) => {
            if (
                selectors.groupTypeIndex(previousState) !== values.groupTypeIndex ||
                selectors.groupKey(previousState) !== values.groupKey
            ) {
                actions.loadGroup()
            }
        },
    }),
})
