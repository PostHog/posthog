import { actions, isBreakpoint, kea, key, listeners, path, props, reducers } from 'kea'

import { ApiConfig } from 'lib/api'

import {
    integrationsBingAdsAccountsRetrieve,
    integrationsGoogleSearchConsoleSitesRetrieve,
} from 'products/integrations/frontend/generated/api'
import type {
    IntegrationAccountApi,
    IntegrationAccountsResponseApi,
} from 'products/integrations/frontend/generated/api.schemas'

import type { integrationAccountsLogicType } from './integrationAccountsLogicType'

/**
 * Per-platform fetcher for the shared `{ accounts }` account contract. Every ad platform that
 * exposes a selectable-account endpoint adds its entry here (keyed by integration `kind`) and the
 * generic logic + selector work unchanged.
 */
const ACCOUNT_FETCHERS: Record<string, (projectId: string, id: number) => Promise<IntegrationAccountsResponseApi>> = {
    'bing-ads': integrationsBingAdsAccountsRetrieve,
    'google-search-console': integrationsGoogleSearchConsoleSitesRetrieve,
}

export const integrationAccountsLogic = kea<integrationAccountsLogicType>([
    props({} as { id: number; kind: string }),
    key((props) => `${props.kind}/${props.id}`),
    path((key) => ['lib', 'integrations', 'integrationAccountsLogic', key]),

    actions({
        loadAccounts: true,
        loadAccountsSuccess: (accounts: IntegrationAccountApi[]) => ({ accounts }),
        loadAccountsFailure: true,
    }),

    reducers({
        accounts: [
            [] as IntegrationAccountApi[],
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
            const fetcher = ACCOUNT_FETCHERS[props.kind]
            if (!fetcher) {
                actions.loadAccountsFailure()
                return
            }
            try {
                const response = await fetcher(String(ApiConfig.getCurrentProjectId()), props.id)
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
