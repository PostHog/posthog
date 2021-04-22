import { kea } from 'kea'
import api from 'lib/api'
import { EventDefition } from '~/types'

export const eventDefinitionsLogic = kea({
    loaders: {
        rawEventDefinitions: [
            [] as EventDefition[],
            {
                loadEventDefinitions: async () => {
                    const response = await api.get('api/projects/@current/event_definitions/')
                    // Handle pagination here
                    return response
                },
            },
        ],
    },
})
