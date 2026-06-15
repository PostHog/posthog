import { actions, afterMount, connect, kea, key, listeners, path, props, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import { teamLogic } from 'scenes/teamLogic'

import type { aiGatewayDetailLogicType } from './aiGatewayDetailLogicType'
import { aiGatewayLogic } from './aiGatewayLogic'
import { fetchGatewayUsage, GatewayUsage } from './gatewayUsage'
import { gatewaysList } from './generated/api'
import { GatewayApi } from './generated/api.schemas'

export interface AIGatewayDetailLogicProps {
    slug: string
}

export type EndpointTab = 'typescript' | 'python' | 'curl'
export type EndpointProvider = 'openai' | 'anthropic'
export type DetailTab = 'usage' | 'connect'

export const aiGatewayDetailLogic = kea<aiGatewayDetailLogicType>([
    path((key) => ['products', 'ai_gateway', 'frontend', 'aiGatewayDetailLogic', key]),
    props({} as AIGatewayDetailLogicProps),
    key((props) => props.slug),
    connect(() => ({
        values: [teamLogic, ['currentTeamId'], aiGatewayLogic, ['gateways']],
        actions: [aiGatewayLogic, ['loadGateways']],
    })),
    actions({
        loadUsage: true,
        setEndpointTab: (tab: EndpointTab) => ({ tab }),
        setEndpointProvider: (provider: EndpointProvider) => ({ provider }),
        setDetailTab: (tab: DetailTab) => ({ tab }),
    }),
    reducers({
        endpointTab: ['typescript' as EndpointTab, { setEndpointTab: (_, { tab }) => tab }],
        endpointProvider: ['openai' as EndpointProvider, { setEndpointProvider: (_, { provider }) => provider }],
        detailTab: ['usage' as DetailTab, { setDetailTab: (_, { tab }) => tab }],
    }),
    loaders(({ props, values }) => ({
        gateway: [
            null as GatewayApi | null,
            {
                // The URL carries the slug (human-readable); resolve it to the gateway.
                loadGateway: async () => {
                    const results = (await gatewaysList(String(values.currentTeamId), { limit: 1000 })).results
                    return results.find((g) => g.slug === props.slug) ?? null
                },
            },
        ],
        usage: [
            null as GatewayUsage | null,
            {
                loadUsage: async () => (props.slug ? await fetchGatewayUsage(props.slug) : null),
            },
        ],
    })),
    listeners(({ actions }) => ({
        loadGatewaySuccess: () => {
            // Keep the team's gateway list warm for the scene header.
            actions.loadGateways()
            actions.loadUsage()
        },
    })),
    afterMount(({ actions }) => actions.loadGateway()),
])
