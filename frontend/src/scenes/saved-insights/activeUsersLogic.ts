import { MakeLogicType, afterMount, kea, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import { hogql } from '~/queries/utils'
import { PersonType } from '~/types'

export interface ActivePersonType extends PersonType {
    activity_count: number
}

export interface activeUsersLogicValues {
    persons: ActivePersonType[]
    personsLoading: boolean
    personsLoadedError: boolean
}

export interface activeUsersLogicActions {
    loadPersons: () => any
    loadPersonsFailure: (error: string, errorObject?: any) => { error: string; errorObject?: any }
    loadPersonsSuccess: (persons: ActivePersonType[], payload?: any) => { persons: ActivePersonType[]; payload?: any }
}

export type activeUsersLogicType = MakeLogicType<activeUsersLogicValues, activeUsersLogicActions>

export const activeUsersLogic = kea<activeUsersLogicType>([
    path(['scenes', 'saved-insights', 'activeUsersLogic']),
    loaders({
        persons: {
            __default: [] as ActivePersonType[],
            loadPersons: async () => {
                // HogQL provides activity ranking that the persons API does not support.
                const query = hogql`
                    SELECT any(distinct_id), count() as activity_count
                    FROM events
                    SAMPLE 10000000
                    WHERE timestamp > now() - INTERVAL 7 DAY
                    GROUP BY person_id
                    ORDER BY activity_count DESC
                    LIMIT 5
                `
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
                        return person ? { ...person, activity_count: counts.get(distinctId) || 0 } : null
                    })
                    .filter((person): person is ActivePersonType => person !== null)
                    .sort((a, b) => b.activity_count - a.activity_count)
            },
        },
    }),
    reducers({
        personsLoadedError: [
            false,
            {
                loadPersons: () => false,
                loadPersonsSuccess: () => false,
                loadPersonsFailure: () => true,
            },
        ],
    }),
    afterMount(({ actions }) => actions.loadPersons()),
])
