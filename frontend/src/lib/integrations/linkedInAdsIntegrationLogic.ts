import { actions, kea, key, path, props } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import { LinkedInAdsAccountType, LinkedInAdsConversionRuleType } from '~/types'

import type { linkedInAdsIntegrationLogicType } from './linkedInAdsIntegrationLogicType'

export const linkedInAdsIntegrationLogic = kea<linkedInAdsIntegrationLogicType>([
    props({} as { id: number }),
    key((props) => props.id),
    path((key) => ['lib', 'integrations', 'linkedInAdsIntegrationLogic', key]),
    actions({
        loadLinkedInAdsConversionRules: (accountId: string) => accountId,
        loadLinkedInAdsAccounts: true,
    }),
    loaders(({ props }) => ({
        linkedInAdsConversionRules: [
            null as LinkedInAdsConversionRuleType[] | null,
            {
                loadLinkedInAdsConversionRules: async (customerId: string) => {
                    const res = await api.integrations.linkedInAdsConversionRules(props.id, customerId)
                    return res.conversionRules
                },
            },
        ],
        linkedInAdsAccounts: [
            null as LinkedInAdsAccountType[] | null,
            {
                loadLinkedInAdsAccounts: async () => {
                    const res = await api.integrations.linkedInAdsAccounts(props.id)
                    return res.adAccounts
                },
            },
        ],
    })),
])
