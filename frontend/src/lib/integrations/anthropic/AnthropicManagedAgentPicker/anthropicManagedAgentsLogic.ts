import { actions, events, kea, key, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { LemonInputSelectOption } from '@posthog/lemon-ui'

import api from 'lib/api'

import { AnthropicManagedAgentType } from '~/types'

import type { anthropicManagedAgentsLogicType } from './anthropicManagedAgentsLogicType'

export const anthropicManagedAgentsLogic = kea<anthropicManagedAgentsLogicType>([
    props({} as { id: number }),
    key((props) => props.id),
    path((key) => ['lib', 'integrations', 'anthropic', 'anthropicManagedAgentsLogic', key]),
    actions({
        loadAnthropicManagedAgents: () => ({}),
        setHasMore: (hasMore: boolean) => ({ hasMore }),
    }),
    reducers({
        hasMore: [false, { setHasMore: (_, { hasMore }) => hasMore }],
    }),
    loaders(({ props, actions }) => ({
        anthropicManagedAgents: [
            [] as AnthropicManagedAgentType[],
            {
                loadAnthropicManagedAgents: async () => {
                    const res = await api.integrations.anthropicManagedAgents(props.id)
                    actions.setHasMore(Boolean(res.has_more))
                    return res.agents ?? []
                },
            },
        ],
    })),
    selectors({
        options: [
            (s) => [s.anthropicManagedAgents],
            (agents): LemonInputSelectOption[] =>
                (agents ?? []).map((a) => ({
                    key: a.id,
                    label: a.version ? `${a.name} (${a.version})` : a.name,
                })),
        ],
        showTruncationHint: [
            (s) => [s.anthropicManagedAgentsLoading, s.hasMore],
            (loading, hasMore): boolean => !loading && hasMore,
        ],
    }),
    events(({ actions }) => ({
        afterMount: () => {
            actions.loadAnthropicManagedAgents()
        },
    })),
])
