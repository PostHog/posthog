import { actions, afterMount, kea, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import type { aiGatewayLogicType } from './aiGatewayLogicType'
import { fetchGatewayUsage, GatewayUsage } from './gatewayUsage'

export type EndpointTab = 'typescript' | 'python' | 'curl'
export type EndpointProvider = 'openai' | 'anthropic'

export const aiGatewayLogic = kea<aiGatewayLogicType>([
    path(['products', 'ai_gateway', 'frontend', 'aiGatewayLogic']),
    actions({
        setEndpointTab: (tab: EndpointTab) => ({ tab }),
        setEndpointProvider: (provider: EndpointProvider) => ({ provider }),
    }),
    reducers({
        endpointTab: ['typescript' as EndpointTab, { setEndpointTab: (_, { tab }) => tab }],
        endpointProvider: ['openai' as EndpointProvider, { setEndpointProvider: (_, { provider }) => provider }],
    }),
    loaders(() => ({
        usage: [
            null as GatewayUsage | null,
            {
                // Project-wide usage across every gateway-attributed event.
                loadUsage: async () => await fetchGatewayUsage(),
            },
        ],
    })),
    afterMount(({ actions }) => {
        actions.loadUsage()
    }),
])
