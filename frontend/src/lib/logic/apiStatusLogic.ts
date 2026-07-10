import { actions, kea, listeners, path, reducers } from 'kea'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { twoFactorLogic } from 'scenes/authentication/two-factor-setup/twoFactorLogic'
import { userLogic } from 'scenes/userLogic'

import type { apiStatusLogicType } from './apiStatusLogicType'

export const apiStatusLogic = kea<apiStatusLogicType>([
    path(['lib', 'apiStatusLogic']),
    actions({
        onApiResponse: (response?: Response, error?: any) => ({ response, error }),
        setInternetConnectionIssue: (issue: boolean) => ({ issue }),
        setTimeSensitiveAuthenticationRequired: (
            required: boolean | [onComplete: () => void, onCancel: () => void]
        ) => ({
            required,
        }),
        setTwoFactorVerificationExpiredToastShown: (shown: boolean) => ({ shown }),
    }),

    reducers({
        internetConnectionIssue: [
            false,
            {
                setInternetConnectionIssue: (_, { issue }) => issue,
            },
        ],

        timeSensitiveAuthenticationRequired: [
            // When a tuple of callbacks is passed, exactly one is called once re-authentication
            // settles: onComplete when it succeeds, onCancel when it's dismissed or fails. Both
            // resolve the awaiting promise (rather than rejecting) so the rejection never escapes
            // through kea's listener machinery as an unhandled exception — callers inspect the
            // resolved boolean to decide whether to proceed.
            false as boolean | [onComplete: () => void, onCancel: () => void],
            {
                setTimeSensitiveAuthenticationRequired: (_, { required }) => required,
            },
        ],

        twoFactorVerificationExpiredToastShown: [
            false,
            {
                setTwoFactorVerificationExpiredToastShown: (_, { shown }) => shown,
            },
        ],
    }),
    listeners(({ cache, actions, values }) => ({
        onApiResponse: async ({ response, error }, breakpoint) => {
            if (error || !response?.status) {
                await breakpoint(50)
                // Likely CORS headers errors (i.e. request failing without reaching Django))
                if (error?.message === 'Failed to fetch') {
                    actions.setInternetConnectionIssue(true)
                }
            }

            if (response?.ok && values.internetConnectionIssue) {
                actions.setInternetConnectionIssue(false)
            }

            try {
                if (response?.status === 403) {
                    const responseData = await response?.json()
                    if (responseData.code === 'sensitive_action_required_reauth') {
                        actions.setTimeSensitiveAuthenticationRequired(true)
                    } else if (
                        responseData.code === 'two_factor_setup_required' &&
                        !values.timeSensitiveAuthenticationRequired &&
                        !twoFactorLogic.findMounted()?.values.isTwoFactorSetupModalOpen
                    ) {
                        twoFactorLogic.findMounted()?.actions.openTwoFactorSetupModal(true)
                    } else if (
                        responseData.code === 'two_factor_verification_required' &&
                        !values.twoFactorVerificationExpiredToastShown
                    ) {
                        actions.setTwoFactorVerificationExpiredToastShown(true)
                        lemonToast.error(
                            'Your session requires re-authentication. You will be logged out to verify your identity again.',
                            {
                                button: {
                                    label: 'Understood',
                                    action: () => {
                                        userLogic.findMounted()?.actions.logout(true)
                                    },
                                },
                                autoClose: false,
                            }
                        )
                    } else if (responseData.code === 'impersonation_read_only') {
                        lemonToast.error(
                            typeof responseData.detail === 'string' && responseData.detail
                                ? responseData.detail
                                : 'This action is not allowed during read-only user impersonation.',
                            { hideButton: true }
                        )
                    }
                }
            } catch {
                // Pass
            }

            if (response?.status === 401) {
                if (!userLogic.findMounted()?.values.user) {
                    // We should only check and logout if we have a user
                    return
                }

                // During impersonation, don't auto-logout on 401.
                // The ImpersonationNotice component handles session expiry
                // via its countdown timer and shows a re-impersonation overlay.
                if (userLogic.findMounted()?.values.user?.is_impersonated) {
                    return
                }

                // api.ts calls this if we see a 401
                const now = Date.now()

                // We don't want to check too often (multiple api calls might fail at once)
                if (now - 10000 > (cache.lastUnauthorizedCheck ?? 0)) {
                    cache.lastUnauthorizedCheck = Date.now()

                    await api.get('api/users/@me/').catch((error: any) => {
                        if (error.status === 401) {
                            userLogic.findMounted()?.actions.logout(true)
                        }
                    })
                }
            }
        },
    })),
])
