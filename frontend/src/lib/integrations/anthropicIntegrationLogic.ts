import { actions, kea, key, path, props } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import { AnthropicAgentType, AnthropicEnvironmentType, AnthropicVaultType } from '~/types'

import type { anthropicIntegrationLogicType } from './anthropicIntegrationLogicType'

export const anthropicIntegrationLogic = kea<anthropicIntegrationLogicType>([
    props({} as { id: number }),
    key((props) => props.id),
    path((key) => ['lib', 'integrations', 'anthropicIntegrationLogic', key]),
    actions({
        loadAnthropicAgents: () => ({}),
        loadAnthropicEnvironments: () => ({}),
        loadAnthropicVaults: () => ({}),
    }),
    loaders(({ props }) => ({
        anthropicAgents: [
            [] as AnthropicAgentType[],
            {
                loadAnthropicAgents: async () => {
                    const res = await api.integrations.anthropicAgents(props.id)
                    return res.agents
                },
            },
        ],
        anthropicEnvironments: [
            [] as AnthropicEnvironmentType[],
            {
                loadAnthropicEnvironments: async () => {
                    const res = await api.integrations.anthropicEnvironments(props.id)
                    return res.environments
                },
            },
        ],
        anthropicVaults: [
            [] as AnthropicVaultType[],
            {
                loadAnthropicVaults: async () => {
                    const res = await api.integrations.anthropicVaults(props.id)
                    return res.vaults
                },
            },
        ],
    })),
])
