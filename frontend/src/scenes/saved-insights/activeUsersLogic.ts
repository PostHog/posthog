import { afterMount, kea, path } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import { hogql } from '~/queries/utils'
import { PersonType } from '~/types'

import type { activeUsersLogicType } from './activeUsersLogicType'

export const activeUsersLogic = kea<activeUsersLogicType>([
    path(['scenes', 'saved-insights', 'activeUsersLogic']),

    loaders({
        persons: {
            __default: [] as PersonType[],
            loadPersons: async () => {
                // HogQL is used here to get activity-based ranking, which the persons API doesn't support
                const query = hogql`
                    SELECT any(distinct_id), count() as activity_count
                    FROM events
                    SAMPLE 0.1
                    WHERE timestamp > now() - INTERVAL 7 DAY
                    GROUP BY person_id
                    ORDER BY activity_count DESC
                    LIMIT 5
                `
                try {
                    const idsResponse = await api.queryHogQL(query, {
                        scene: 'SavedInsights',
                        productKey: 'persons',
                    })
                    const distinctIds = (idsResponse.results || []).map((row) => row[0] as string)
                    const personResults = await Promise.all(
                        distinctIds.map((id) => api.persons.list({ distinct_id: id, limit: 1 }))
                    )
                    return personResults.flatMap((r) => r.results).filter(Boolean)
                } catch (error) {
                    console.error('Failed to load active users:', error)
                    return []
                }
            },
        },
    }),

    afterMount(({ actions }) => actions.loadPersons()),
])
