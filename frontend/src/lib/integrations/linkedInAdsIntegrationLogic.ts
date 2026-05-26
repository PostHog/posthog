import { actions, kea, key, listeners, path, props, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api, { ApiError } from 'lib/api'

import { LinkedInAdsAccountType, LinkedInAdsConversionRuleType } from '~/types'

import type { linkedInAdsIntegrationLogicType } from './linkedInAdsIntegrationLogicType'

const extractErrorMessage = (error: unknown, fallback: string): string => {
    if (error instanceof ApiError) {
        return error.detail || error.message || fallback
    }
    if (error instanceof Error) {
        return error.message || fallback
    }
    return fallback
}

export const linkedInAdsIntegrationLogic = kea<linkedInAdsIntegrationLogicType>([
    props({} as { id: number }),
    key((props) => props.id),
    path((key) => ['lib', 'integrations', 'linkedInAdsIntegrationLogic', key]),
    actions({
        loadLinkedInAdsConversionRules: (accountId: string) => accountId,
        loadLinkedInAdsAccounts: true,
        setLinkedInAdsConversionRulesError: (error: string | null) => ({ error }),
        setLinkedInAdsAccountsError: (error: string | null) => ({ error }),
    }),
    reducers({
        linkedInAdsConversionRulesError: [
            null as string | null,
            {
                setLinkedInAdsConversionRulesError: (_, { error }) => error,
                loadLinkedInAdsConversionRules: () => null,
            },
        ],
        linkedInAdsAccountsError: [
            null as string | null,
            {
                setLinkedInAdsAccountsError: (_, { error }) => error,
                loadLinkedInAdsAccounts: () => null,
            },
        ],
    }),
    loaders(({ props }) => ({
        linkedInAdsConversionRules: [
            null as LinkedInAdsConversionRuleType[] | null,
            {
                loadLinkedInAdsConversionRules: async (customerId: string) => {
                    const res = await api.integrations.linkedInAdsConversionRules(props.id, customerId)
                    return res.conversionRules
                },
            },
        ],
        linkedInAdsAccounts: [
            null as LinkedInAdsAccountType[] | null,
            {
                loadLinkedInAdsAccounts: async () => {
                    const res = await api.integrations.linkedInAdsAccounts(props.id)
                    return res.adAccounts
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
        loadLinkedInAdsConversionRulesFailure: ({ error, errorObject }) => {
            const message = extractErrorMessage(errorObject ?? error, 'Failed to load LinkedIn Ads conversion rules.')
            actions.setLinkedInAdsConversionRulesError(message)
            lemonToast.error(message)
        },
        loadLinkedInAdsAccountsFailure: ({ error, errorObject }) => {
            const message = extractErrorMessage(errorObject ?? error, 'Failed to load LinkedIn Ads accounts.')
            actions.setLinkedInAdsAccountsError(message)
            lemonToast.error(message)
        },
    })),
])
