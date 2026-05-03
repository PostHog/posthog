import { actions, kea, key, path, props } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import {
    AnthropicManagedAgentEnvironmentType,
    AnthropicManagedAgentType,
    AnthropicManagedAgentVaultType,
} from '~/types'

import type { anthropicManagedAgentsLogicType } from './anthropicManagedAgentsLogicType'

export const anthropicManagedAgentsLogic = kea<anthropicManagedAgentsLogicType>([
    props({} as { id: number }),
    key((props) => props.id),
    path((key) => ['lib', 'integrations', 'anthropicManagedAgentsLogic', key]),
    actions({
        loadAnthropicManagedAgents: () => ({}),
        loadAnthropicManagedAgentEnvironments: () => ({}),
        loadAnthropicManagedAgentVaults: () => ({}),
    }),
    loaders(({ props }) => ({
        anthropicManagedAgents: [
            [] as AnthropicManagedAgentType[],
            {
                loadAnthropicManagedAgents: async () => {
                    const res = await api.integrations.anthropicManagedAgents(props.id)
                    return res.agents
                },
            },
        ],
        anthropicManagedAgentEnvironments: [
            [] as AnthropicManagedAgentEnvironmentType[],
            {
                loadAnthropicManagedAgentEnvironments: async () => {
                    const res = await api.integrations.anthropicManagedAgentEnvironments(props.id)
                    return res.environments
                },
            },
        ],
        anthropicManagedAgentVaults: [
            [] as AnthropicManagedAgentVaultType[],
            {
                loadAnthropicManagedAgentVaults: async () => {
                    const res = await api.integrations.anthropicManagedAgentVaults(props.id)
                    return res.vaults
                },
            },
        ],
    })),
])
