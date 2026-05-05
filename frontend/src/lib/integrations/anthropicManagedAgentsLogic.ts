import { actions, kea, key, path, props, reducers } from 'kea'
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
        setAgentsHasMore: (hasMore: boolean) => ({ hasMore }),
        setEnvironmentsHasMore: (hasMore: boolean) => ({ hasMore }),
        setVaultsHasMore: (hasMore: boolean) => ({ hasMore }),
    }),
    reducers({
        anthropicManagedAgentsHasMore: [false, { setAgentsHasMore: (_, { hasMore }) => hasMore }],
        anthropicManagedAgentEnvironmentsHasMore: [false, { setEnvironmentsHasMore: (_, { hasMore }) => hasMore }],
        anthropicManagedAgentVaultsHasMore: [false, { setVaultsHasMore: (_, { hasMore }) => hasMore }],
    }),
    loaders(({ props, actions }) => ({
        anthropicManagedAgents: [
            [] as AnthropicManagedAgentType[],
            {
                loadAnthropicManagedAgents: async () => {
                    const res = await api.integrations.anthropicManagedAgents(props.id)
                    actions.setAgentsHasMore(Boolean(res.has_more))
                    return res.agents ?? []
                },
            },
        ],
        anthropicManagedAgentEnvironments: [
            [] as AnthropicManagedAgentEnvironmentType[],
            {
                loadAnthropicManagedAgentEnvironments: async () => {
                    const res = await api.integrations.anthropicManagedAgentEnvironments(props.id)
                    actions.setEnvironmentsHasMore(Boolean(res.has_more))
                    return res.environments ?? []
                },
            },
        ],
        anthropicManagedAgentVaults: [
            [] as AnthropicManagedAgentVaultType[],
            {
                loadAnthropicManagedAgentVaults: async () => {
                    const res = await api.integrations.anthropicManagedAgentVaults(props.id)
                    actions.setVaultsHasMore(Boolean(res.has_more))
                    return res.vaults ?? []
                },
            },
        ],
    })),
])
