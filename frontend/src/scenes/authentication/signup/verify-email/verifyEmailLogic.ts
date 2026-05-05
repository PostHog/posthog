import { actions, connect, kea, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { getRelativeNextPath } from 'lib/utils'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import type { verifyEmailLogicType } from './verifyEmailLogicType'

/** Delay between a successful verification and redirecting to the app.
 * Must stay in sync with the `VerifyEmail__Progress` animation duration in VerifyEmail.scss. */
export const VERIFY_EMAIL_REDIRECT_DELAY_MS = 2000

/**
 * Decide where to send a verified user when no `?next=` redirect is present.
 *
 * Fresh signups (no completed onboarding for any product) go straight to `/onboarding`,
 * skipping the brief homepage flash that the legacy `/` redirect produced before
 * sceneLogic detected they needed onboarding and re-redirected.
 *
 * Already-onboarded users (typically refreshing the verify URL after a previous
 * successful verification) go to `urls.default()` so they don't land on the
 * product-selection page and accidentally re-run onboarding.
 */
const resolvePostVerifyDefault = (values: {
    user?: { team?: { has_completed_onboarding_for?: Record<string, boolean> } | null } | null
}): string => {
    // If `loadUser` hasn't completed by the time we resolve a redirect target (a
    // race that can happen when verify completes quickly), prefer the safe
    // `urls.default()` over `urls.onboarding()`. sceneLogic will route the
    // already-onboarded user away from `/` once user state hydrates; the
    // opposite mistake (sending an onboarded user back through onboarding) is
    // worse because they may inadvertently flip product-completion state.
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
    path(['scenes', 'authentication', 'verifyEmailLogic']),
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
                validateEmailToken: async ({ uuid, token }: { uuid: string; token: string }, breakpoint) => {
                    try {
                        const response = await api.create<{ success: boolean; token?: string; requires_2fa?: boolean }>(
                            `api/users/verify_email/`,
                            { token, uuid }
                        )
                        actions.setView('success')
                        await breakpoint(VERIFY_EMAIL_REDIRECT_DELAY_MS)

                        const nextUrl = getRelativeNextPath(new URLSearchParams(location.search).get('next'), location)
                        if (response.requires_2fa) {
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
                    } catch (e: any) {
                        // If the token is invalid but the user is already logged in and verified,
                        // treat this as success (likely a page refresh after the first successful POST)
                        const user = (values as any).user
                        if (user?.is_email_verified) {
                            actions.setView('success')
                            await breakpoint(VERIFY_EMAIL_REDIRECT_DELAY_MS)
                            const nextUrl = getRelativeNextPath(
                                new URLSearchParams(location.search).get('next'),
                                location
                            )
                            // this url is validated in getRelativeNextPath as either being relative or on the same origin
                            // nosemgrep: javascript.browser.security.open-redirect.js-open-redirect
                            location.href = nextUrl || resolvePostVerifyDefault(values)
                            return { success: true, token, uuid }
                        }
                        actions.setView('invalid')
                        return { success: false, errorCode: e.code, errorDetail: e.detail }
                    }
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
    urlToAction(({ actions }) => ({
        '/verify_email/:uuid': ({ uuid }) => {
            if (uuid) {
                actions.setUuid(uuid)
                actions.setView('pending')
            }
        },
        '/verify_email/:uuid/:token': ({ uuid, token }) => {
            if (token && uuid) {
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
