import { actions, afterMount, connect, kea, key, listeners, path, props, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'

import { HogQLQuery, NodeKind } from '~/queries/schema/schema-general'

import type { aiGatewayDetailLogicType } from './aiGatewayDetailLogicType'
import { aiGatewayLogic } from './aiGatewayLogic'
import { gatewaysRetrieve } from './generated/api'
import { GatewayApi } from './generated/api.schemas'

export interface AIGatewayDetailLogicProps {
    id: string
}

export interface GatewayUsage {
    requests: number
    inputTokens: number
    outputTokens: number
    costUsd: number
}

export type EndpointTab = 'curl' | 'openai' | 'anthropic'

// Window for the usage panel; the gateway slug arrives on $ai_generation events
// from the gateway (ai-gateway #80), so this is empty until that ships.
const USAGE_WINDOW_DAYS = 30

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
                    if (!slug) {
                        return null
                    }
                    const query: HogQLQuery = {
                        kind: NodeKind.HogQLQuery,
                        query: `
                            SELECT
                                count() AS requests,
                                sum(toFloat(properties.$ai_input_tokens)) AS input_tokens,
                                sum(toFloat(properties.$ai_output_tokens)) AS output_tokens,
                                round(sum(toFloat(properties.$ai_total_cost_usd)), 4) AS cost_usd
                            FROM events
                            WHERE event = '$ai_generation'
                                AND properties.$ai_gateway_slug = {slug}
                                AND timestamp >= now() - INTERVAL ${USAGE_WINDOW_DAYS} DAY
                        `,
                        values: { slug },
                    }
                    const response = await api.query(query)
                    const row = response.results?.[0] ?? []
                    return {
                        requests: Number(row[0]) || 0,
                        inputTokens: Number(row[1]) || 0,
                        outputTokens: Number(row[2]) || 0,
                        costUsd: Number(row[3]) || 0,
                    }
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
