import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { humanFriendlyCurrency } from 'lib/utils/numbers'
import { teamLogic } from 'scenes/teamLogic'

import type { aiGatewayLogicType } from './aiGatewayLogicType'
import {
    buildSpendChartData,
    fetchGatewaySpendByDay,
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
        usage: [
            (s) => [s.modelUsage],
            (modelUsage): GatewayUsage =>
                modelUsage.reduce(
                    (acc, model) => ({
                        requests: acc.requests + model.requests,
                        inputTokens: acc.inputTokens + model.inputTokens,
                        outputTokens: acc.outputTokens + model.outputTokens,
                        costUsd: acc.costUsd + model.costUsd,
                    }),
                    { requests: 0, inputTokens: 0, outputTokens: 0, costUsd: 0 }
                ),
        ],
        spendChart: [
            (s) => [s.spendSeries, teamLogic.selectors.timezone],
            (spendSeries, timezone): { data: number[]; labels: string[] } => buildSpendChartData(spendSeries, timezone),
        ],
        hasUsage: [(s) => [s.modelUsage], (modelUsage): boolean => modelUsage.length > 0],
    }),
    listeners(({ values, actions }) => ({
        confirmTopUp: () => {
            lemonToast.info(`Top up of ${humanFriendlyCurrency(values.topUpAmountUsd)} is mocked for now.`)
            actions.closeTopUpModal()
        },
        loadSpendSeriesFailure: ({ error }) => {
            lemonToast.error(`Couldn't load gateway spend: ${error}`)
        },
        loadModelUsageFailure: ({ error }) => {
            lemonToast.error(`Couldn't load gateway usage: ${error}`)
        },
    })),
    afterMount(({ actions }) => {
        actions.loadSpendSeries()
        actions.loadModelUsage()
    }),
])
