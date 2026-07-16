import { actions, kea, key, listeners, path, props, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import { ApiConfig } from 'lib/api'

import { externalDataSourcesOauthAccountsRetrieve } from 'products/warehouse_sources/frontend/generated/api'
import type { IntegrationAccountApi } from 'products/warehouse_sources/frontend/generated/api.schemas'

import type { integrationAccountsLogicType } from './integrationAccountsLogicType'

const SEARCH_DEBOUNCE_MS = 300

export const integrationAccountsLogic = kea<integrationAccountsLogicType>([
    props({} as { id: number; sourceType: string }),
    key((props) => `${props.sourceType}/${props.id}`),
    path((key) => ['lib', 'integrations', 'integrationAccountsLogic', key]),

    actions({
        setSearch: (search: string) => ({ search }),
    }),

    loaders(({ props, values }) => ({
        accounts: [
            [] as IntegrationAccountApi[],
            {
                loadAccounts: async () => {
                    const response = await externalDataSourcesOauthAccountsRetrieve(
                        String(ApiConfig.getCurrentProjectId()),
                        {
                            source_type: props.sourceType,
                            integration_id: props.id,
                            // Sources with large resource lists (e.g. GitHub repositories) filter server-side;
                            // small-list sources ignore it and the endpoint filters their returned list.
                            search: values.search || undefined,
                        }
                    )
                    return response.accounts
                },
            },
        ],
    })),

    reducers({
        search: ['', { setSearch: (_, { search }) => search }],
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

    listeners(({ actions }) => ({
        setSearch: async (_, breakpoint) => {
            // Debounce keystrokes into a single server-side query.
            await breakpoint(SEARCH_DEBOUNCE_MS)
            actions.loadAccounts()
        },
    })),
])
