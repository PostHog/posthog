import { actions, events, kea, key, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { LemonInputSelectOption } from '@posthog/lemon-ui'

import api from 'lib/api'

import { AnthropicManagedAgentVaultType } from '~/types'

import type { anthropicManagedAgentVaultsLogicType } from './anthropicManagedAgentVaultsLogicType'

export const anthropicManagedAgentVaultsLogic = kea<anthropicManagedAgentVaultsLogicType>([
    props({} as { id: number }),
    key((props) => props.id),
    path((key) => ['lib', 'integrations', 'anthropic', 'anthropicManagedAgentVaultsLogic', key]),
    actions({
        loadAnthropicManagedAgentVaults: () => ({}),
        setHasMore: (hasMore: boolean) => ({ hasMore }),
    }),
    reducers({
        hasMore: [false, { setHasMore: (_, { hasMore }) => hasMore }],
    }),
    loaders(({ props, actions }) => ({
        anthropicManagedAgentVaults: [
            [] as AnthropicManagedAgentVaultType[],
            {
                loadAnthropicManagedAgentVaults: async () => {
                    const res = await api.integrations.anthropicManagedAgentVaults(props.id)
                    actions.setHasMore(Boolean(res.has_more))
                    return res.vaults ?? []
                },
            },
        ],
    })),
    selectors({
        options: [
            (s) => [s.anthropicManagedAgentVaults],
            (vaults): LemonInputSelectOption[] => (vaults ?? []).map((v) => ({ key: v.id, label: v.display_name })),
        ],
        showTruncationHint: [
            (s) => [s.anthropicManagedAgentVaultsLoading, s.hasMore],
            (loading, hasMore): boolean => !loading && hasMore,
        ],
    }),
    events(({ actions }) => ({
        afterMount: () => {
            actions.loadAnthropicManagedAgentVaults()
        },
    })),
])
