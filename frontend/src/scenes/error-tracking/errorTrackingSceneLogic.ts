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
                        query: hogql`SELECT first_value(properties), count(), count(distinct properties.$session_id)
                                FROM events e
                                WHERE event = '$exception'
                                -- grouping by message for now, will eventually be predefined $exception_group_id
                                GROUP BY properties.$exception_message`,
                    }

                    const res = await api.query(query)

                    return res.results.map((r) => {
                        const eventProperties = JSON.parse(r[0])
                        return {
                            sampleEvent: { event: '$exception', properties: eventProperties },
                            title: eventProperties['$exception_message'] || 'No message',
                            occurrences: r[2],
                            unique_sessions: r[3],
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
