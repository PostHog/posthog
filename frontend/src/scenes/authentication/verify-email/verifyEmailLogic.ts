import { actions, connect, kea, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { getRelativeNextPath } from 'lib/utils/url'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import type { verifyEmailLogicType } from './verifyEmailLogicType'

// Must stay in sync with the `VerifyEmail__Progress` animation duration in VerifyEmail.scss.
export const VERIFY_EMAIL_REDIRECT_DELAY_MS = 2000

const resolvePostVerifyDefault = (values: {
    user?: { team?: { has_completed_onboarding_for?: Record<string, boolean> } | null } | null
}): string => {
    if (!values.user) {
        return urls.default()
    }
    const completedMap = values.user.team?.has_completed_onboarding_for ?? {}
    const hasCompletedSomething = Object.values(completedMap).some(Boolean)
    return hasCompletedSomething ? urls.default() : urls.onboarding()
}

export interface ResponseType {
    success: boolean
    errorCode?: string
    errorDetail?: string
}

export interface ValidatedTokenResponseType extends ResponseType {
    token?: string
    uuid?: string
}

export const verifyEmailLogic = kea<verifyEmailLogicType>([
    path(['scenes', 'authentication', 'verify-email', 'verifyEmailLogic']),
    connect(() => ({ values: [userLogic, ['user']] })),
    actions({
        setView: (view: 'verify' | 'pending' | 'invalid' | 'success' | null) => ({ view }),
        setUuid: (uuid: string | null) => ({ uuid }),
        requestVerificationLink: (uuid: string) => ({ uuid }),
    }),
    loaders(({ actions, values }) => ({
        validatedEmailToken: [
            null as ValidatedTokenResponseType | null,
            {
                validateEmailToken: async (
                    { uuid, token }: { uuid: string; token: string },
                    breakpoint
                ): Promise<ValidatedTokenResponseType> => {
                    let response: { success: boolean; token?: string; requires_2fa?: boolean } | null = null
                    // Only the API call belongs in the try/catch. The success-animation
                    // breakpoint below must stay outside it: if it threw inside a catch
                    // its cancellation would be swallowed and the loader would resolve to
                    // `undefined`, tripping the auto-generated success reducer's guard.
                    try {
                        response = await api.create<{ success: boolean; token?: string; requires_2fa?: boolean }>(
                            `api/users/verify_email/`,
                            { token, uuid }
                        )
                    } catch (e: any) {
                        // The token can fail to validate if the email was already verified
                        // (e.g. the link was opened twice) — treat an already-verified user
                        // as success, otherwise surface the invalid-token view.
                        const user = (values as any).user
                        if (!user?.is_email_verified) {
                            actions.setView('invalid')
                            return { success: false, errorCode: e.code, errorDetail: e.detail }
                        }
                    }

                    actions.setView('success')
                    // Outside the try/catch on purpose: if the logic unmounts or the route
                    // re-matches during this delay, this breakpoint throws and kea-loaders
                    // aborts the stale run cleanly instead of dispatching an undefined result.
                    await breakpoint(VERIFY_EMAIL_REDIRECT_DELAY_MS)

                    const nextUrl = getRelativeNextPath(new URLSearchParams(location.search).get('next'), location)
                    if (response?.requires_2fa) {
                        lemonToast.success(
                            'Email verified! Please log in with your password to complete two-factor authentication.'
                        )
                        router.actions.push(urls.login(), nextUrl ? { next: nextUrl } : {})
                        return { success: true, token, uuid }
                    }

                    // this url is validated in getRelativeNextPath as either being relative or on the same origin
                    // this url is also secret and so we can trust it's not attacker controlled
                    // nosemgrep: javascript.browser.security.open-redirect.js-open-redirect
                    location.href = nextUrl || resolvePostVerifyDefault(values)
                    return { success: true, token, uuid }
                },
            },
        ],
        newlyRequestedVerificationLink: [
            null as boolean | null,
            {
                requestVerificationLink: async ({ uuid }: { uuid: string }) => {
                    try {
                        await api.create(`api/users/request_email_verification/`, { uuid })
                        lemonToast.success(
                            'A new verification link has been sent to the associated email address. Please check your inbox.'
                        )
                        return true
                    } catch (e: any) {
                        if (e.code === 'throttled') {
                            lemonToast.error(
                                'You have requested a new verification link too many times. Please try again later.'
                            )
                            return false
                        }
                        lemonToast.error(
                            'Requesting verification link failed. Please try again later or contact support.'
                        )
                        return false
                    }
                },
            },
        ],
    })),
    reducers({
        view: [
            null as 'pending' | 'verify' | 'invalid' | 'success' | null,
            {
                setView: (_, { view }) => view,
            },
        ],
        uuid: [
            null as string | null,
            {
                setUuid: (_, { uuid }) => uuid,
            },
        ],
    }),
    urlToAction(({ actions, values }) => ({
        '/verify_email/:uuid': ({ uuid }) => {
            if (uuid) {
                actions.setUuid(uuid)
                actions.setView('pending')
            }
        },
        '/verify_email/:uuid/:token': ({ uuid, token }) => {
            // Skip if a validation is already in flight (including during the
            // post-success redirect delay) — re-dispatching would cancel the
            // in-flight breakpoint and restart the flow needlessly.
            if (token && uuid && !values.validatedEmailTokenLoading) {
                actions.setUuid(uuid)
                actions.setView('verify')
                actions.validateEmailToken({ uuid, token })
            }
        },
        '/verify_email': () => {
            actions.setView('invalid')
        },
    })),
])
