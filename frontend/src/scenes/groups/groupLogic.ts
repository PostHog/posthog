import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { urlToAction } from 'kea-router'
import posthog from 'posthog-js'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { toParams } from 'lib/utils'
import { capitalizeFirstLetter } from 'lib/utils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { groupDisplayId } from 'scenes/persons/GroupActorDisplay'
import { Scene } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { SIDE_PANEL_CONTEXT_KEY, SidePanelSceneContext } from '~/layout/navigation-3000/sidepanel/types'
import { groupsModel } from '~/models/groupsModel'
import { defaultDataTableColumns } from '~/queries/nodes/DataTable/utils'
import { DataTableNode, Node, NodeKind } from '~/queries/schema/schema-general'
import { isDataTableNode } from '~/queries/utils'
import { ActivityScope, Breadcrumb, Group, GroupTypeIndex, PropertyFilterType, PropertyOperator } from '~/types'

import { revenueAnalyticsLogic } from 'products/revenue_analytics/frontend/revenueAnalyticsLogic'

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
    tabId?: string
}

export const groupLogic = kea<groupLogicType>([
    props({} as GroupLogicProps),
    key(({ groupKey, groupTypeIndex, tabId }) => `${groupTypeIndex}-${groupKey}-${tabId}`),
    path((key) => ['scenes', 'groups', 'groupLogic', key]),
    connect(() => ({
        actions: [groupsModel, ['createDetailDashboard']],
        values: [
            teamLogic,
            ['currentTeamId'],
            groupsModel,
            ['groupTypes', 'aggregationLabel'],
            featureFlagLogic,
            ['featureFlags'],
            revenueAnalyticsLogic,
            ['isRevenueAnalyticsEnabled'],
        ],
    })),
    actions(() => ({
        setGroupData: (group: Group) => ({ group }),
        setGroupTab: (groupTab: string | null) => ({ groupTab }),
        setGroupEventsQuery: (query: Node) => ({ query }),
        editProperty: (key: string, newValue?: string | number | boolean | null) => ({ key, newValue }),
        deleteProperty: (key: string) => ({ key }),
    })),
    loaders(({ values, props }) => ({
        groupData: [
            null as Group | null,
            {
                loadGroup: async () => {
                    const params = { group_type_index: props.groupTypeIndex, group_key: props.groupKey }
                    const url = `api/environments/${values.currentTeamId}/groups/find?${toParams(params)}`
                    return await api.get(url)
                },
            },
        ],
        groupRevenueAnalyticsData: [
            null as { mrr: number | null; lifetimeValue: number | null } | null,
            {
                loadGroupRevenueAnalyticsData: async () => {
                    // Check if revenue analytics is available
                    if (!values.isRevenueAnalyticsEnabled) {
                        return null
                    }

                    try {
                        const query = {
                            kind: NodeKind.HogQLQuery,
                            query: `
                                SELECT
                                    mrr,
                                    revenue as lifetimeValue
                                FROM groups_revenue_analytics
                                WHERE group_key = {groupKey}
                            `,
                            values: { groupKey: props.groupKey },
                        }

                        const result = await api.query(query)

                        const row = (result as any).results?.[0]
                        if (!row) {
                            return null
                        }

                        return {
                            mrr: row[0] ?? null,
                            lifetimeValue: row[1] ?? null,
                        }
                    } catch (error) {
                        // Silently fall back to group properties
                        posthog.captureException(error, { tag: 'group_revenue_analytics_data_query_failed' })
                        return null
                    }
                },
            },
        ],
    })),
    listeners(({ actions, values }) => ({
        editProperty: async ({ key, newValue }) => {
            const group = values.groupData

            if (group) {
                let parsedValue = newValue

                // Instrumentation stuff
                let action: 'added' | 'updated'
                const oldPropertyType =
                    group.group_properties[key] === null ? 'null' : typeof group.group_properties[key]
                let newPropertyType: string = typeof newValue

                // If the property is a number, store it as a number
                const attemptedParsedNumber = Number(newValue)
                if (!Number.isNaN(attemptedParsedNumber) && typeof newValue !== 'boolean') {
                    parsedValue = attemptedParsedNumber
                    newPropertyType = 'number'
                }

                const lowercaseValue = typeof parsedValue === 'string' && parsedValue.toLowerCase()
                if (lowercaseValue === 'true' || lowercaseValue === 'false' || lowercaseValue === 'null') {
                    parsedValue = lowercaseValue === 'true' ? true : lowercaseValue === 'null' ? null : false
                    newPropertyType = parsedValue !== null ? 'boolean' : 'null'
                }

                let updatedProperties = { ...group.group_properties }
                if (!Object.keys(updatedProperties).includes(key)) {
                    updatedProperties = { [key]: parsedValue, ...updatedProperties } // To add property at the top (if new)
                    action = 'added'
                } else {
                    updatedProperties[key] = parsedValue
                    action = 'updated'
                }

                actions.setGroupData({ ...group, group_properties: updatedProperties }) // To update the UI immediately while the request is being processed
                await api.groups.updateProperty(group.group_type_index, group.group_key, key, parsedValue)
                lemonToast.success(`Group property ${action}`)

                eventUsageLogic.actions.reportGroupPropertyUpdated(
                    action,
                    Object.keys(group.group_properties).length,
                    oldPropertyType,
                    newPropertyType
                )
            }
        },
        deleteProperty: async ({ key }) => {
            const group = values.groupData

            if (group) {
                const updatedProperties = { ...group.group_properties }
                delete updatedProperties[key]

                actions.setGroupData({ ...group, group_properties: updatedProperties }) // To update the UI immediately
                await api.groups.deleteProperty(group.group_type_index, group.group_key, key)
                lemonToast.success(`Group property deleted`)

                eventUsageLogic.actions.reportGroupPropertyUpdated('removed', 1, undefined, undefined)
            }
        },
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
        groupData: [
            null as Group | null,
            {
                setGroupData: (_, { group }) => group,
            },
        ],
    }),
    selectors({
        logicProps: [() => [(_, props) => props], (props): GroupLogicProps => props],

        groupTypeName: [
            (s, p) => [s.aggregationLabel, p.groupTypeIndex],
            (aggregationLabel, index): string => aggregationLabel(index).singular,
        ],
        groupTypeNamePlural: [
            (s, p) => [s.aggregationLabel, p.groupTypeIndex],
            (aggregationLabel, index): string => aggregationLabel(index).plural,
        ],
        groupType: [
            (s, p) => [s.groupTypes, p.groupTypeIndex],
            (groupTypes, index): string | null => groupTypes.get(index as GroupTypeIndex)?.group_type ?? null,
        ],
        groupTypeDetailDashboard: [
            (s, p) => [s.groupTypes, p.groupTypeIndex],
            (groupTypes, index): number | null => groupTypes.get(index as GroupTypeIndex)?.detail_dashboard ?? null,
        ],
        // Combine revenue analytics with group properties, prioritizing analytics
        effectiveMRR: [
            (s) => [s.groupRevenueAnalyticsData, s.groupData],
            (revenueData, groupData): { value: number | null; source: 'revenue-analytics' | 'properties' | null } => {
                // Use pre-calculated data if available
                if (revenueData?.mrr !== null && revenueData?.mrr !== undefined) {
                    return { value: revenueData.mrr, source: 'revenue-analytics' }
                }
                // Fallback to group properties
                const mrrValue = groupData?.group_properties?.mrr
                if (typeof mrrValue === 'number' && !isNaN(mrrValue)) {
                    return { value: mrrValue, source: 'properties' }
                }
                return { value: null, source: null }
            },
        ],
        effectiveLifetimeValue: [
            (s) => [s.groupRevenueAnalyticsData, s.groupData],
            (revenueData, groupData): { value: number | null; source: 'revenue-analytics' | 'properties' | null } => {
                // Use pre-calculated data if available
                if (revenueData?.lifetimeValue !== null && revenueData?.lifetimeValue !== undefined) {
                    return { value: revenueData.lifetimeValue, source: 'revenue-analytics' }
                }
                // Fallback to group properties
                const ltv = groupData?.group_properties?.customer_lifetime_value
                if (typeof ltv === 'number' && !isNaN(ltv)) {
                    return { value: ltv, source: 'properties' }
                }
                return { value: null, source: null }
            },
        ],
        hasRevenueData: [
            (s) => [s.effectiveMRR, s.effectiveLifetimeValue],
            (mrr, ltv): boolean => mrr.value !== null || ltv.value !== null,
        ],
        breadcrumbs: [
            (s, p) => [s.groupTypeName, p.groupTypeIndex, p.groupKey, s.groupData],
            (groupTypeName, groupTypeIndex, groupKey, groupData): Breadcrumb[] => {
                const breadcrumbs: Breadcrumb[] = []
                breadcrumbs.push({
                    key: Scene.DataManagement,
                    name: 'People',
                    path: urls.persons(),
                    iconType: 'persons',
                })
                breadcrumbs.push({
                    key: groupTypeIndex,
                    name: capitalizeFirstLetter(groupTypeName),
                    path: urls.groups(String(groupTypeIndex)),
                    iconType: 'group',
                })
                breadcrumbs.push({
                    key: [Scene.Group, `${groupTypeIndex}-${groupKey}`],
                    name: groupDisplayId(groupKey, groupData?.group_properties || {}),
                    path: urls.group(String(groupTypeIndex), groupKey),
                    iconType: 'group',
                })

                return breadcrumbs
            },
        ],
        [SIDE_PANEL_CONTEXT_KEY]: [
            (s, p) => [p.groupTypeIndex, p.groupKey, s.featureFlags],
            (groupTypeIndex, groupKey, featureFlags): SidePanelSceneContext | null => {
                if (!featureFlags[FEATURE_FLAGS.CUSTOMER_ANALYTICS]) {
                    return null
                }
                return {
                    activity_scope: ActivityScope.GROUP,
                    activity_item_id: `${groupTypeIndex}-${groupKey}`,
                }
            },
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
        actions.loadGroupRevenueAnalyticsData()
    }),
])
