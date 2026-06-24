import { actions, isBreakpoint, kea, key, listeners, path, props, reducers } from 'kea'

import { ApiConfig } from 'lib/api'

import { integrationsBingAdsAccountsRetrieve } from 'products/integrations/frontend/generated/api'
import type { BingAdsAccountApi } from 'products/integrations/frontend/generated/api.schemas'

import type { bingAdsIntegrationLogicType } from './bingAdsIntegrationLogicType'

export const bingAdsIntegrationLogic = kea<bingAdsIntegrationLogicType>([
    props({} as { id: number }),
    key((props) => props.id),
    path((key) => ['lib', 'integrations', 'bingAdsIntegrationLogic', key]),

    actions({
        loadAccounts: true,
        loadAccountsSuccess: (accounts: BingAdsAccountApi[]) => ({ accounts }),
        loadAccountsFailure: true,
    }),

    reducers({
        accounts: [
            [] as BingAdsAccountApi[],
            {
                loadAccounts: () => [],
                loadAccountsSuccess: (_, { accounts }) => accounts,
            },
        ],
        accountsLoading: [
            false,
            {
                loadAccounts: () => true,
                loadAccountsSuccess: () => false,
                loadAccountsFailure: () => false,
            },
        ],
    }),

    listeners(({ actions, props }) => ({
        loadAccounts: async (_, breakpoint) => {
            try {
                const response = await integrationsBingAdsAccountsRetrieve(
                    String(ApiConfig.getCurrentProjectId()),
                    props.id
                )
                await breakpoint()
                actions.loadAccountsSuccess(response.accounts)
            } catch (e: any) {
                if (isBreakpoint(e)) {
                    throw e
                }
                actions.loadAccountsFailure()
            }
        },
    })),
])
