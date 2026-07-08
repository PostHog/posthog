import { kea, key, path, props, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import { ApiConfig } from 'lib/api'

import { externalDataSourcesOauthAccountsRetrieve } from 'products/warehouse_sources/frontend/generated/api'
import type { IntegrationAccountApi } from 'products/warehouse_sources/frontend/generated/api.schemas'

import type { integrationAccountsLogicType } from './integrationAccountsLogicType'

export const integrationAccountsLogic = kea<integrationAccountsLogicType>([
    props({} as { id: number; sourceType: string }),
    key((props) => `${props.sourceType}/${props.id}`),
    path((key) => ['lib', 'integrations', 'integrationAccountsLogic', key]),

    loaders(({ props }) => ({
        accounts: [
            [] as IntegrationAccountApi[],
            {
                loadAccounts: async (_, breakpoint) => {
                    const response = await externalDataSourcesOauthAccountsRetrieve(
                        String(ApiConfig.getCurrentProjectId()),
                        {
                            source_type: props.sourceType,
                            integration_id: props.id,
                        }
                    )
                    breakpoint()
                    return response.accounts
                },
            },
        ],
    })),

    reducers({
        // Surface the backend's actionable 400 message (e.g. "reconnect the integration") instead of
        // falling back to a generic "no accounts" empty state. Cleared when a fresh load starts or succeeds.
        accountsError: [
            null as string | null,
            {
                loadAccounts: () => null,
                loadAccountsSuccess: () => null,
                loadAccountsFailure: (_, { error, errorObject }) =>
                    errorObject?.data?.detail ?? errorObject?.detail ?? error ?? null,
            },
        ],
    }),
])
