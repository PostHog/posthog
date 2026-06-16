import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { humanFriendlyCurrency } from 'lib/utils'

import type { aiGatewayLogicType } from './aiGatewayLogicType'
import {
    buildSpendChartData,
    fetchGatewaySpendByDay,
    fetchGatewayUsage,
    fetchGatewayUsageByModel,
    GatewayModelUsage,
    GatewaySpendPoint,
    GatewayUsage,
} from './gatewayUsage'

export type EndpointTab = 'typescript' | 'python' | 'curl'
export type EndpointProvider = 'openai' | 'anthropic'

export const aiGatewayLogic = kea<aiGatewayLogicType>([
    path(['products', 'ai_gateway', 'frontend', 'aiGatewayLogic']),
    actions({
        setEndpointTab: (tab: EndpointTab) => ({ tab }),
        setEndpointProvider: (provider: EndpointProvider) => ({ provider }),
        openTopUpModal: true,
        closeTopUpModal: true,
        setTopUpAmount: (amountUsd: number) => ({ amountUsd }),
        confirmTopUp: true,
    }),
    reducers({
        endpointTab: ['typescript' as EndpointTab, { setEndpointTab: (_, { tab }) => tab }],
        endpointProvider: ['openai' as EndpointProvider, { setEndpointProvider: (_, { provider }) => provider }],
        isTopUpModalOpen: [false, { openTopUpModal: () => true, closeTopUpModal: () => false }],
        topUpAmountUsd: [25, { setTopUpAmount: (_, { amountUsd }) => amountUsd }],
    }),
    loaders(() => ({
        usage: [
            null as GatewayUsage | null,
            {
                loadUsage: async () => await fetchGatewayUsage(),
            },
        ],
        spendSeries: [
            [] as GatewaySpendPoint[],
            {
                loadSpendSeries: async () => await fetchGatewaySpendByDay(),
            },
        ],
        modelUsage: [
            [] as GatewayModelUsage[],
            {
                loadModelUsage: async () => await fetchGatewayUsageByModel(),
            },
        ],
    })),
    selectors({
        spendChart: [
            (s) => [s.spendSeries],
            (spendSeries): { data: number[]; labels: string[] } => buildSpendChartData(spendSeries),
        ],
    }),
    listeners(({ values, actions }) => ({
        confirmTopUp: () => {
            lemonToast.info(`Top up of ${humanFriendlyCurrency(values.topUpAmountUsd)} is mocked for now.`)
            actions.closeTopUpModal()
        },
    })),
    afterMount(({ actions }) => {
        actions.loadUsage()
        actions.loadSpendSeries()
        actions.loadModelUsage()
    }),
])
