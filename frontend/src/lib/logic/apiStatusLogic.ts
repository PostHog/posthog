import { actions, kea, listeners, path, reducers } from 'kea'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { limitExceededLogic } from 'lib/components/LimitExceededModal/limitExceededLogic'
import { twoFactorLogic } from 'scenes/authentication/twoFactorLogic'
import { userLogic } from 'scenes/userLogic'

import type { apiStatusLogicType } from './apiStatusLogicType'

export const apiStatusLogic = kea<apiStatusLogicType>([
    path(['lib', 'apiStatusLogic']),
    actions({
        onApiResponse: (response?: Response, error?: any) => ({ response, error }),
        setInternetConnectionIssue: (issue: boolean) => ({ issue }),
        setTimeSensitiveAuthenticationRequired: (required: boolean | [resolve: () => void, reject: () => void]) => ({
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
            // When a tuple with resolve/reject is passed, one of these will be called
            // when re-authentication succeeds or fails/is dismissed
            false as boolean | [resolve: () => void, reject: () => void],
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
                    }
                }
            } catch {
                // Pass
            }

            if (response?.status === 402) {
                try {
                    // Clone so downstream callers (which parse the body again) still see it.
                    const responseData = await response.clone().json()
                    if (responseData?.type === 'limit_exceeded' && responseData?.extra?.limit_key) {
                        const teamId = userLogic.findMounted()?.values.user?.team?.id ?? null
                        if (teamId) {
                            limitExceededLogic.findMounted()?.actions.showLimitExceededModal(responseData.extra, teamId)
                        }
                    }
                } catch {
                    // Non-fatal: if the body isn't JSON, we just don't surface the modal.
                }
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
