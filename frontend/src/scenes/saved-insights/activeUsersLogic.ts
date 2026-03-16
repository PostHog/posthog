import { afterMount, kea, path } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import { hogql } from '~/queries/utils'
import { PersonType } from '~/types'

import type { activeUsersLogicType } from './activeUsersLogicType'

export interface ActivePersonType extends PersonType {
    activity_count: number
}

export const activeUsersLogic = kea<activeUsersLogicType>([
    path(['scenes', 'saved-insights', 'activeUsersLogic']),

    loaders({
        persons: {
            __default: [] as ActivePersonType[],
            loadPersons: async () => {
                // HogQL is used here to get activity-based ranking, which the persons API doesn't support
                const query = hogql`
                    SELECT any(distinct_id), count() as activity_count
                    FROM events
                    SAMPLE 10000000
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
                    const results = idsResponse.results || []
                    const distinctIds = results.map((row) => row[0] as string)
                    const counts = new Map(results.map((row) => [row[0] as string, row[1] as number]))

                    const personsMap = await api.persons.getByDistinctIds(distinctIds)

                    return distinctIds
                        .map((distinctId) => {
                            const person = personsMap[distinctId]
                            if (!person) {
                                return null
                            }
                            return { ...person, activity_count: counts.get(distinctId) || 0 }
                        })
                        .filter((p): p is ActivePersonType => !!p)
                        .sort((a, b) => b.activity_count - a.activity_count)
                } catch (error) {
                    console.error('Failed to load active users:', error)
                    return []
                }
            },
        },
    }),

    afterMount(({ actions }) => actions.loadPersons()),
])
