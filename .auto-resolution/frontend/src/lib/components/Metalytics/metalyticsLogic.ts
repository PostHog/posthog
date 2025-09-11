import { connect, kea, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'

import api from 'lib/api'
import { membersLogic } from 'scenes/organization/membersLogic'

import { sidePanelContextLogic } from '~/layout/navigation-3000/sidepanel/panels/sidePanelContextLogic'
import { SidePanelSceneContext } from '~/layout/navigation-3000/sidepanel/types'
import { hogql } from '~/queries/utils'

import type { metalyticsLogicType } from './metalyticsLogicType'

export const metalyticsLogic = kea<metalyticsLogicType>([
    path(['lib', 'components', 'metalytics', 'metalyticsLogic']),
    connect(() => ({
        values: [sidePanelContextLogic, ['sceneSidePanelContext'], membersLogic, ['members']],
    })),

    loaders(({ values }) => ({
        viewCount: [
            null as { views: number; users: number } | null,
            {
                loadViewCount: async () => {
                    const query = hogql`
                        SELECT SUM(count) AS count, COUNT(DISTINCT app_source_id) AS unique_users
                        FROM app_metrics
                        WHERE app_source = 'metalytics'
                        AND instance_id = ${values.instanceId}`

                    // NOTE: I think this gets cached heavily - how to correctly invalidate?
                    const response = await api.queryHogQL(query, { refresh: 'force_blocking' })
                    const result = response.results as number[][]
                    return {
                        views: result[0][0],
                        users: result[0][1],
                    }
                },
            },
        ],
        recentUsers: [
            [] as string[],
            {
                loadUsersLast30days: async () => {
                    const query = hogql`
                        SELECT DISTINCT app_source_id
                        FROM app_metrics
                        WHERE app_source = 'metalytics'
                        AND instance_id = ${values.instanceId}
                        AND timestamp >= NOW() - INTERVAL 30 DAY
                        ORDER BY timestamp DESC`

                    const response = await api.queryHogQL(query, { refresh: 'force_blocking' })
                    return response.results.map((result) => result[0]) as string[]
                },
            },
        ],
    })),

    selectors({
        instanceId: [
            (s) => [s.sceneSidePanelContext],
            (sidePanelContext: SidePanelSceneContext) =>
                sidePanelContext?.activity_item_id
                    ? `${sidePanelContext.activity_scope}:${sidePanelContext.activity_item_id}`
                    : null,
        ],
        scope: [
            (s) => [s.sceneSidePanelContext],
            (sidePanelContext: SidePanelSceneContext) => sidePanelContext?.activity_scope,
        ],

        recentUserMembers: [
            (s) => [s.recentUsers, s.members],
            (recentUsers, members) => {
                if (!members || !recentUsers) {
                    return []
                }
                // Filter members whose IDs match the recentUsers array
                const filteredMembers = members.filter((member) => recentUsers.includes(String(member.user.id)))
                return filteredMembers
            },
        ],
    }),

    subscriptions(({ actions }) => ({
        instanceId: async (instanceId) => {
            if (instanceId) {
                actions.loadViewCount()
                actions.loadUsersLast30days()

                await api.create('/api/projects/@current/metalytics/', {
                    metric_name: 'viewed',
                    instance_id: instanceId,
                })
            }
        },
    })),
])
