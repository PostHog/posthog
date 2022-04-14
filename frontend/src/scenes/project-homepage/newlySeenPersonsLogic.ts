import { kea } from 'kea'

import { PersonType } from '~/types'
import api from 'lib/api'

import type { newlySeenPersonsLogicType } from './newlySeenPersonsLogicType'
export const newlySeenPersonsLogic = kea<newlySeenPersonsLogicType>({
    path: ['scenes', 'project-homepage', 'newlySeenPersonsLogic'],
    loaders: () => ({
        persons: [
            [] as PersonType[],
            {
                loadPersons: async () => {
                    const response = await api.get(`api/person/`)
                    return response.results
                },
            },
        ],
    }),

    events: ({ actions }) => ({
        afterMount: () => {
            actions.loadPersons()
        },
    }),
})
