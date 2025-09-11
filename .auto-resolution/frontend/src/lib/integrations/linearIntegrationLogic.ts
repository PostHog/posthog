import { actions, kea, key, path, props } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import { LinearTeamType } from '~/types'

import type { linearIntegrationLogicType } from './linearIntegrationLogicType'

export const linearIntegrationLogic = kea<linearIntegrationLogicType>([
    props({} as { id: number }),
    key((props) => props.id),
    path((key) => ['lib', 'integrations', 'linearIntegrationLogic', key]),
    actions({
        loadAllLinearTeams: () => ({}),
    }),

    loaders(({ props }) => ({
        linearTeams: [
            [] as LinearTeamType[],
            {
                loadAllLinearTeams: async () => {
                    const res = await api.integrations.linearTeams(props.id)
                    return res.teams
                },
            },
        ],
    })),
])
