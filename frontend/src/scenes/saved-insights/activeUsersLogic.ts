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
                const query = hogql`
                    SELECT person.id, any(person.properties), any(person.created_at), count() as count
                    FROM events
                    WHERE timestamp > now() - INTERVAL 7 DAY
                    GROUP BY person.id
                    ORDER BY count DESC
                    LIMIT 5
                `
                const response = await api.queryHogQL(query, { scene: 'SavedInsights', productKey: 'persons' })

                return (response.results || []).map((row) => {
                    const properties = row[1] ? JSON.parse(row[1]) : {}
                    return {
                        id: row[0],
                        uuid: row[0],
                        distinct_ids: [row[0]],
                        properties: properties,
                        created_at: row[2],
                        is_identified: false,
                        name: properties.email || properties.name || row[0],
                    } as unknown as PersonType
                })
            },
        },
    }),

    afterMount(({ actions }) => actions.loadPersons()),
])
