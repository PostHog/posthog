import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { lazyLoaders } from 'kea-loaders'
import { router } from 'kea-router'

import api from 'lib/api'
import { isEmptyObject } from 'lib/utils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { urls } from 'scenes/urls'

import { getQueryBasedInsightModel } from '~/queries/nodes/InsightViz/utils'
import { InsightType, QueryBasedInsightModel } from '~/types'

import { customerAnalyticsConfigLogic } from '../../customerAnalyticsConfigLogic'
import type { journeyTemplatePickerLogicType } from './journeyTemplatePickerLogicType'

export type JourneyTemplateKey = 'signup_conversion' | 'free_to_paid' | 'scratch'

export const journeyTemplatePickerLogic = kea<journeyTemplatePickerLogicType>([
    path([
        'products',
        'customer_analytics',
        'frontend',
        'scenes',
        'CustomerJourneyTemplatesScene',
        'journeyTemplatePickerLogic',
    ]),

    connect(() => ({
        actions: [
            eventUsageLogic,
            ['reportCustomerJourneyTemplateSelected', 'reportCustomerJourneyExistingFunnelSelected'],
        ],
        values: [customerAnalyticsConfigLogic, ['signupEvent', 'signupPageviewEvent', 'paymentEvent']],
    })),

    actions({
        toggleExistingFunnels: true,
        selectTemplate: (templateKey: JourneyTemplateKey) => ({ templateKey }),
        selectExistingFunnel: (insightId: number) => ({ insightId }),
        setSearchTerm: (term: string) => ({ term }),
        loadFunnels: true,
        resetState: true,
    }),

    lazyLoaders(({ values }) => ({
        funnels: {
            __default: [] as QueryBasedInsightModel[],
            loadFunnels: async (_, breakpoint) => {
                await breakpoint(300)
                const response = await api.insights.list({
                    saved: true,
                    insight: InsightType.FUNNELS,
                    ...(values.searchTerm ? { search: values.searchTerm } : {}),
                })
                return response.results.map((insight) => getQueryBasedInsightModel(insight))
            },
        },
    })),

    reducers({
        showExistingFunnels: [
            false,
            {
                toggleExistingFunnels: (state) => !state,
                resetState: () => false,
            },
        ],
        searchTerm: [
            '',
            {
                setSearchTerm: (_, { term }) => term,
                resetState: () => '',
            },
        ],
    }),

    selectors({
        isSignupConversionAvailable: [
            (s) => [s.signupPageviewEvent, s.signupEvent],
            (signupPageviewEvent, signupEvent): boolean =>
                !isEmptyObject(signupPageviewEvent) && !isEmptyObject(signupEvent),
        ],
        isFreeToPaidAvailable: [
            (s) => [s.signupEvent, s.paymentEvent],
            (signupEvent, paymentEvent): boolean => !isEmptyObject(signupEvent) && !isEmptyObject(paymentEvent),
        ],
    }),

    listeners(({ actions, values }) => ({
        selectTemplate: ({ templateKey }) => {
            actions.reportCustomerJourneyTemplateSelected(templateKey)
            if (templateKey === 'scratch') {
                router.actions.push(urls.customerJourneyBuilder())
            } else {
                router.actions.push(urls.customerJourneyBuilder() + '?template=' + templateKey)
            }
        },
        selectExistingFunnel: ({ insightId }) => {
            actions.reportCustomerJourneyExistingFunnelSelected(insightId)
            router.actions.push(urls.customerJourneyBuilder() + '?fromInsight=' + insightId)
        },
        toggleExistingFunnels: () => {
            if (values.showExistingFunnels) {
                actions.loadFunnels()
            }
        },
        setSearchTerm: () => {
            actions.loadFunnels()
        },
    })),

    afterMount(({ actions }) => {
        actions.resetState()
    }),
])
