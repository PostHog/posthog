import { actions, kea, key, path, props, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import { ApiConfig, ApiError } from 'lib/api'

import { externalDataSourcesOauthAccountsRetrieve } from 'products/warehouse_sources/frontend/generated/api'
import type { IntegrationAccountApi } from 'products/warehouse_sources/frontend/generated/api.schemas'

import type { integrationAccountsLogicType } from './integrationAccountsLogicType'

export const integrationAccountsLogic = kea<integrationAccountsLogicType>([
    props({} as { id: number; sourceType: string }),
    key((props) => `${props.sourceType}/${props.id}`),
    path((key) => ['lib', 'integrations', 'integrationAccountsLogic', key]),

    actions({
        setAccountsError: (error: string | null) => ({ error }),
    }),

    loaders(({ props, actions }) => ({
        accounts: [
            [] as IntegrationAccountApi[],
            {
                loadAccounts: async () => {
                    try {
                        const response = await externalDataSourcesOauthAccountsRetrieve(
                            String(ApiConfig.getCurrentProjectId()),
                            {
                                source_type: props.sourceType,
                                integration_id: props.id,
                            }
                        )
                        return response.accounts
                    } catch (error) {
                        // A 400 is the backend's expected, actionable "reconnect your account" response for
                        // invalid/expired credentials. Swallow it so the rejection never reaches posthog-js's
                        // global exception handler as an uncaught error, but still surface its message in the UI.
                        // Anything else re-throws so genuine bugs remain visible in error tracking.
                        if (error instanceof ApiError && error.status === 400) {
                            actions.setAccountsError(error.data?.detail ?? error.detail ?? error.message ?? null)
                            return []
                        }
                        throw error
                    }
                },
            },
        ],
    })),

    reducers({
        // Surface the backend's actionable 400 message (e.g. "reconnect the integration") instead of
        // falling back to a generic "no accounts" empty state. Cleared when a fresh load starts.
        accountsError: [
            null as string | null,
            {
                loadAccounts: () => null,
                setAccountsError: (_, { error }) => error,
                loadAccountsFailure: (_, { error, errorObject }) =>
                    errorObject?.data?.detail ?? errorObject?.detail ?? error ?? null,
            },
        ],
    }),
])
