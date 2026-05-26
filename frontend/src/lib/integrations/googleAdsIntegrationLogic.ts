import { actions, kea, key, listeners, path, props, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api, { ApiError } from 'lib/api'

import { GoogleAdsConversionActionType } from '~/types'

import type { googleAdsIntegrationLogicType } from './googleAdsIntegrationLogicType'

const extractErrorMessage = (error: unknown, fallback: string): string => {
    if (error instanceof ApiError) {
        return error.detail || error.message || fallback
    }
    if (error instanceof Error) {
        return error.message || fallback
    }
    return fallback
}

export const googleAdsIntegrationLogic = kea<googleAdsIntegrationLogicType>([
    props({} as { id: number }),
    key((props) => props.id),
    path((key) => ['lib', 'integrations', 'googleAdsIntegrationLogic', key]),
    actions({
        loadGoogleAdsConversionActions: (customerId: string, parentId: string) => ({ customerId, parentId }),
        loadGoogleAdsAccessibleAccounts: true,
        setGoogleAdsConversionActionsError: (error: string | null) => ({ error }),
        setGoogleAdsAccessibleAccountsError: (error: string | null) => ({ error }),
    }),
    reducers({
        googleAdsConversionActionsError: [
            null as string | null,
            {
                setGoogleAdsConversionActionsError: (_, { error }) => error,
                loadGoogleAdsConversionActions: () => null,
            },
        ],
        googleAdsAccessibleAccountsError: [
            null as string | null,
            {
                setGoogleAdsAccessibleAccountsError: (_, { error }) => error,
                loadGoogleAdsAccessibleAccounts: () => null,
            },
        ],
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
    // Without these listeners, kea-loaders' default behavior re-emits the loader error,
    // posthog-js captures it as an unhandled exception, and the UI never gets a usable
    // hook to show the backend ValidationError message to the user. Converting failures
    // into reducer state + a toast keeps the noise out of error tracking and gives the
    // picker components something to render instead of a stuck spinner.
    listeners(({ actions }) => ({
        loadGoogleAdsConversionActionsFailure: ({ error, errorObject }) => {
            const message = extractErrorMessage(errorObject ?? error, 'Failed to load Google Ads conversion actions.')
            actions.setGoogleAdsConversionActionsError(message)
            lemonToast.error(message)
        },
        loadGoogleAdsAccessibleAccountsFailure: ({ error, errorObject }) => {
            const message = extractErrorMessage(errorObject ?? error, 'Failed to load Google Ads accounts.')
            actions.setGoogleAdsAccessibleAccountsError(message)
            lemonToast.error(message)
        },
    })),
])
