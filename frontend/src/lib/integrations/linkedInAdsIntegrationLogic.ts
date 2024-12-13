import { actions, kea, key, path, props } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'

import { LinkedInAdsConversionActionType } from '~/types'

import type { linkedInAdsIntegrationLogicType } from './linkedInAdsIntegrationLogicType'

export const linkedInAdsIntegrationLogic = kea<linkedInAdsIntegrationLogicType>([
    props({} as { id: number }),
    key((props) => props.id),
    path((key) => ['lib', 'integrations', 'linkedInAdsIntegrationLogic', key]),
    actions({
        loadLinkedInAdsConversionActions: (customerId: string) => customerId,
        loadLinkedInAdsAccessibleAccounts: true,
    }),

    loaders(({ props }) => ({
        linkedInAdsConversionActions: [
            null as LinkedInAdsConversionActionType[] | null,
            {
                loadLinkedInAdsConversionActions: async (customerId: string) => {
                    const res = await api.integrations.linkedInAdsConversionActions(props.id, customerId)
                    return res.conversionActions
                },
            },
        ],
        linkedInAdsAccessibleAccounts: [
            null as { id: string }[] | null,
            {
                loadLinkedInAdsAccessibleAccounts: async () => {
                    const res = await api.integrations.linkedInAdsAccounts(props.id)
                    return res.accessibleAccounts
                },
            },
        ],
    })),
])
