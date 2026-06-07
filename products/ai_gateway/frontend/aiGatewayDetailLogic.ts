import { actions, afterMount, connect, kea, key, listeners, path, props, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import { teamLogic } from 'scenes/teamLogic'

import type { aiGatewayDetailLogicType } from './aiGatewayDetailLogicType'
import { aiGatewayLogic } from './aiGatewayLogic'
import { fetchGatewayUsage, GatewayUsage } from './gatewayUsage'
import { gatewaysRetrieve } from './generated/api'
import { GatewayApi } from './generated/api.schemas'

export interface AIGatewayDetailLogicProps {
    id: string
}

export type EndpointTab = 'curl' | 'openai' | 'anthropic'

export const aiGatewayDetailLogic = kea<aiGatewayDetailLogicType>([
    path((key) => ['products', 'ai_gateway', 'frontend', 'aiGatewayDetailLogic', key]),
    props({} as AIGatewayDetailLogicProps),
    key((props) => props.id),
    connect(() => ({
        values: [teamLogic, ['currentTeamId'], aiGatewayLogic, ['gateways']],
        actions: [aiGatewayLogic, ['loadCredentials', 'loadGateways']],
    })),
    actions({
        loadUsage: true,
        setEndpointTab: (tab: EndpointTab) => ({ tab }),
    }),
    reducers({
        endpointTab: ['curl' as EndpointTab, { setEndpointTab: (_, { tab }) => tab }],
    }),
    loaders(({ props, values }) => ({
        gateway: [
            null as GatewayApi | null,
            {
                loadGateway: async () => await gatewaysRetrieve(String(values.currentTeamId), props.id),
            },
        ],
        usage: [
            null as GatewayUsage | null,
            {
                loadUsage: async () => {
                    const slug = values.gateway?.slug
                    return slug ? await fetchGatewayUsage(slug) : null
                },
            },
        ],
    })),
    listeners(({ props, actions }) => ({
        loadGatewaySuccess: () => {
            // The move-credential menu needs the team's other gateways; credentials
            // and usage need this gateway's slug, now loaded.
            actions.loadGateways()
            actions.loadCredentials({ gatewayId: props.id })
            actions.loadUsage()
        },
    })),
    afterMount(({ actions }) => actions.loadGateway()),
])
