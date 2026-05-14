import { afterMount, connect, kea, path } from 'kea'
import { loaders } from 'kea-loaders'

import { teamLogic } from 'scenes/teamLogic'

import type { agentApplicationsLogicType } from './agentApplicationsLogicType'
import { agentApplicationsList } from './generated/api'
import type { AgentApplicationApi } from './generated/api.schemas'

export const agentApplicationsLogic = kea<agentApplicationsLogicType>([
    path(['products', 'agent_stack', 'frontend', 'agentApplicationsLogic']),
    connect(() => ({
        values: [teamLogic, ['currentProjectId']],
    })),
    loaders(({ values }) => ({
        applications: [
            [] as AgentApplicationApi[],
            {
                loadApplications: async () => {
                    const response = await agentApplicationsList(String(values.currentProjectId))
                    return response.results
                },
            },
        ],
    })),
    afterMount(({ actions }) => {
        actions.loadApplications()
    }),
])
