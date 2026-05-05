import { actions, events, kea, key, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { LemonInputSelectOption } from '@posthog/lemon-ui'

import api from 'lib/api'

import { AnthropicManagedAgentEnvironmentType } from '~/types'

import type { anthropicManagedAgentEnvironmentsLogicType } from './anthropicManagedAgentEnvironmentsLogicType'

export const anthropicManagedAgentEnvironmentsLogic = kea<anthropicManagedAgentEnvironmentsLogicType>([
    props({} as { id: number }),
    key((props) => props.id),
    path((key) => ['lib', 'integrations', 'anthropic', 'anthropicManagedAgentEnvironmentsLogic', key]),
    actions({
        loadAnthropicManagedAgentEnvironments: () => ({}),
        setHasMore: (hasMore: boolean) => ({ hasMore }),
    }),
    reducers({
        hasMore: [false, { setHasMore: (_, { hasMore }) => hasMore }],
    }),
    loaders(({ props, actions }) => ({
        anthropicManagedAgentEnvironments: [
            [] as AnthropicManagedAgentEnvironmentType[],
            {
                loadAnthropicManagedAgentEnvironments: async () => {
                    const res = await api.integrations.anthropicManagedAgentEnvironments(props.id)
                    actions.setHasMore(Boolean(res.has_more))
                    return res.environments ?? []
                },
            },
        ],
    })),
    selectors({
        options: [
            (s) => [s.anthropicManagedAgentEnvironments],
            (environments): LemonInputSelectOption[] => (environments ?? []).map((e) => ({ key: e.id, label: e.name })),
        ],
        showTruncationHint: [
            (s) => [s.anthropicManagedAgentEnvironmentsLoading, s.hasMore],
            (loading, hasMore): boolean => !loading && hasMore,
        ],
    }),
    events(({ actions }) => ({
        afterMount: () => {
            actions.loadAnthropicManagedAgentEnvironments()
        },
    })),
])
