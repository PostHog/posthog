import { afterMount, kea, path } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'

import { HogQLQuery, NodeKind } from '~/queries/schema'
import { hogql } from '~/queries/utils'
import { ErrorTrackingGroup } from '~/types'

import type { errorTrackingSceneLogicType } from './errorTrackingSceneLogicType'

export const errorTrackingSceneLogic = kea<errorTrackingSceneLogicType>([
    path(['scenes', 'error-tracking', 'errorTrackingSceneLogic']),

    loaders(() => ({
        errorGroups: [
            [] as ErrorTrackingGroup[],
            {
                loadErrorGroups: async () => {
                    const query: HogQLQuery = {
                        kind: NodeKind.HogQLQuery,
                        query: hogql`SELECT first_value(properties), count(), count(distinct e.$session_id), count(distinct e.distinct_id)
                                FROM events e
                                WHERE event = '$exception'
                                -- grouping by message for now, will eventually be predefined $exception_group_id
                                GROUP BY e.properties.$exception_type`,
                    }

                    const res = await api.query(query)

                    return res.results.map((r) => {
                        const eventProperties = JSON.parse(r[0])
                        return {
                            id: eventProperties['$exception_type'],
                            title: eventProperties['$exception_type'] || 'Error',
                            description: eventProperties['$exception_message'],
                            occurrences: r[1],
                            uniqueSessions: r[2],
                            uniqueUsers: r[3],
                        }
                    })
                },
            },
        ],
    })),

    afterMount(({ actions }) => {
        actions.loadErrorGroups()
    }),
])
