import { actions, kea, key, path, props } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import { GoogleAdsConversionActionType } from '~/types'

import type { googleAdsIntegrationLogicType } from './googleAdsIntegrationLogicType'

export const googleAdsIntegrationLogic = kea<googleAdsIntegrationLogicType>([
    props({} as { id: number }),
    key((props) => props.id),
    path((key) => ['lib', 'integrations', 'googleAdsIntegrationLogic', key]),
    actions({
        loadGoogleAdsConversionActions: (customerId: string, parentId: string) => ({ customerId, parentId }),
        loadGoogleAdsAccessibleAccounts: true,
    }),
    loaders(({ props }) => ({
        googleAdsConversionActions: [
            null as GoogleAdsConversionActionType[] | null,
            {
                loadGoogleAdsConversionActions: async ({
                    customerId,
                    parentId,
                }: {
                    customerId: string
                    parentId: string
                }) => {
                    const res = await api.integrations.googleAdsConversionActions(props.id, {
                        customerId,
                        parentId,
                    })
                    return res.conversionActions
                },
            },
        ],
        googleAdsAccessibleAccounts: [
            null as { id: string; level: string; parent_id: string; name: string }[] | null,
            {
                loadGoogleAdsAccessibleAccounts: async () => {
                    const res = await api.integrations.googleAdsAccounts(props.id)
                    return res.accessibleAccounts
                },
            },
        ],
    })),
])
