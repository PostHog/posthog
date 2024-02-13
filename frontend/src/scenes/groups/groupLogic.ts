import { actions, afterMount, connect, kea, key, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { urlToAction } from 'kea-router'
import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { toParams } from 'lib/utils'
import { capitalizeFirstLetter } from 'lib/utils'
import { groupDisplayId } from 'scenes/persons/GroupActorDisplay'
import { Scene } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { groupsModel } from '~/models/groupsModel'
import { defaultDataTableColumns } from '~/queries/nodes/DataTable/utils'
import { DataTableNode, Node, NodeKind } from '~/queries/schema'
import { isDataTableNode } from '~/queries/utils'
import { Breadcrumb, Group, GroupTypeIndex, PropertyFilterType, PropertyOperator } from '~/types'

import type { groupLogicType } from './groupLogicType'

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

export type GroupLogicProps = {
    groupTypeIndex: number
    groupKey: string
}

export const groupLogic = kea<groupLogicType>([
    props({} as GroupLogicProps),
    key((props) => `${props.groupTypeIndex}-${props.groupKey}`),
    path((key) => ['scenes', 'groups', 'groupLogic', key]),
    connect({
        values: [
            teamLogic,
            ['currentTeamId'],
            groupsModel,
            ['groupTypes', 'aggregationLabel'],
            featureFlagLogic,
            ['featureFlags'],
        ],
    }),
    actions(() => ({
        setGroupTab: (groupTab: string | null) => ({ groupTab }),
        setGroupEventsQuery: (query: Node) => ({ query }),
    })),
    loaders(({ values, props }) => ({
        groupData: [
            null as Group | null,
            {
                loadGroup: async () => {
                    const params = { group_type_index: props.groupTypeIndex, group_key: props.groupKey }
                    const url = `api/projects/${values.currentTeamId}/groups/find?${toParams(params)}`
                    return await api.get(url)
                },
            },
        ],
    })),
    reducers({
        groupTab: [
            null as string | null,
            {
                setGroupTab: (_, { groupTab }) => groupTab,
            },
        ],
        groupEventsQuery: [
            null as DataTableNode | null,
            {
                setGroupEventsQuery: (_, { query }) => (isDataTableNode(query) ? query : null),
            },
        ],
    }),
    selectors({
        logicProps: [() => [(_, props) => props], (props): GroupLogicProps => props],

        showCustomerSuccessDashboards: [
            (s) => [s.featureFlags],
            (featureFlags) => featureFlags[FEATURE_FLAGS.CS_DASHBOARDS],
        ],
        groupTypeName: [
            (s, p) => [s.aggregationLabel, p.groupTypeIndex],
            (aggregationLabel, index): string => aggregationLabel(index).singular,
        ],
        groupType: [
            (s, p) => [s.groupTypes, p.groupTypeIndex],
            (groupTypes, index): string | null => groupTypes.get(index as GroupTypeIndex)?.group_type ?? null,
        ],
        breadcrumbs: [
            (s, p) => [s.groupTypeName, p.groupTypeIndex, p.groupKey, s.groupData],
            (groupTypeName, groupTypeIndex, groupKey, groupData): Breadcrumb[] => [
                {
                    key: Scene.DataManagement,
                    name: 'People',
                    path: urls.persons(),
                },
                {
                    key: groupTypeIndex,
                    name: capitalizeFirstLetter(groupTypeName),
                    path: urls.groups(String(groupTypeIndex)),
                },
                {
                    key: [Scene.Group, `${groupTypeIndex}-${groupKey}`],
                    name: groupDisplayId(groupKey, groupData?.group_properties || {}),
                    path: urls.group(String(groupTypeIndex), groupKey),
                },
            ],
        ],
    }),
    urlToAction(({ actions }) => ({
        '/groups/:groupTypeIndex/:groupKey(/:groupTab)': ({ groupTab }) => {
            actions.setGroupTab(groupTab || null)
        },
    })),

    afterMount(({ actions, props }) => {
        actions.loadGroup()
        actions.setGroupEventsQuery(getGroupEventsQuery(props.groupTypeIndex, props.groupKey))
    }),
])
