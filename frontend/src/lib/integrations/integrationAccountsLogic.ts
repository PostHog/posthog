import { actions, isBreakpoint, kea, key, listeners, path, props, reducers } from 'kea'

import { ApiConfig } from 'lib/api'

import { externalDataSourcesOauthAccountsRetrieve } from 'products/warehouse_sources/frontend/generated/api'
import type { IntegrationAccountApi } from 'products/warehouse_sources/frontend/generated/api.schemas'

import type { integrationAccountsLogicType } from './integrationAccountsLogicType'

export const integrationAccountsLogic = kea<integrationAccountsLogicType>([
    props({} as { id: number; sourceType: string }),
    key((props) => `${props.sourceType}/${props.id}`),
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
            try {
                const response = await externalDataSourcesOauthAccountsRetrieve(
                    String(ApiConfig.getCurrentProjectId()),
                    {
                        source_type: props.sourceType,
                        integration_id: props.id,
                    }
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
