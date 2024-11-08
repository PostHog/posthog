import { actions, connect, kea, key, path, props } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

// import { SlackChannelType } from '~/types'
type GoogleAdsConversionActionType = {
    id: string
    name: string
}

import type { googleAdsIntegrationLogicType } from './googleAdsIntegrationLogicType'

export const googleAdsIntegrationLogic = kea<googleAdsIntegrationLogicType>([
    props({} as { id: number }),
    key((props) => props.id),
    path((key) => ['lib', 'integrations', 'googleAdsIntegrationLogic', key]),
    connect({
        values: [preflightLogic, ['siteUrlMisconfigured', 'preflight']],
    }),
    actions({
        loadGoogleAdsConversionActions: (customerId: string) => customerId,
        loadGoogleAdsAccessibleAccounts: true,
    }),

    loaders(({ props }) => ({
        googleAdsConversionActions: [
            null as GoogleAdsConversionActionType[] | null,
            {
                loadGoogleAdsConversionActions: async (customerId: string) => {
                    const res = await api.integrations.googleAdsConversionActions(props.id, customerId)
                    return res.conversionActions
                },
            },
        ],
        googleAdsAccessibleAccounts: [
            null as string[] | null,
            {
                loadGoogleAdsAccessibleAccounts: async () => {
                    const res = await api.integrations.googleAdsAccounts(props.id)
                    return res.accessibleAccounts
                },
            },
        ],
    })),
])
