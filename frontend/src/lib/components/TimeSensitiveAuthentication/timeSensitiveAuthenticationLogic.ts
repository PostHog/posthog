import {
    type PublicKeyCredentialRequestOptionsJSON,
    type UserVerificationRequirement,
    startAuthentication,
} from '@simplewebauthn/browser'
import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'
import posthog from 'posthog-js'

import api, { ApiError } from 'lib/api'
import { Dayjs, dayjs } from 'lib/dayjs'
import { apiStatusLogic } from 'lib/logic/apiStatusLogic'
import { PrecheckResponseType } from 'scenes/authentication/loginLogic'
import { userLogic } from 'scenes/userLogic'

import { modalInterruptionTrackingLogic } from './modalInterruptionTrackingLogic'
import type { timeSensitiveAuthenticationLogicType } from './timeSensitiveAuthenticationLogicType'

export interface ReauthenticationForm {
    password: string
    token?: string
}

export interface TwoFAMethodsResponse {
    has_totp: boolean
    has_passkeys: boolean
}

const LOOKAHEAD_EXPIRY_SECONDS = 60 * 5

export const timeSensitiveAuthenticationLogic = kea<timeSensitiveAuthenticationLogicType>([
    path(['lib', 'components', 'timeSensitiveAuthenticationLogic']),
    connect(() => ({
        values: [
            apiStatusLogic,
            ['timeSensitiveAuthenticationRequired'],
            userLogic,
            ['user'],
            modalInterruptionTrackingLogic,
            ['interruptedForm'],
        ],
        actions: [apiStatusLogic, ['setTimeSensitiveAuthenticationRequired'], userLogic, ['loadUser']],
        logic: [modalInterruptionTrackingLogic],
    })),
    actions({
        setDismissedReauthentication: (value: boolean) => ({ value }),
        setRequiresTwoFactor: (value: boolean) => ({ value }),
        checkReauthentication: true,
        beginPasskey2FA: true,
        checkPasskeysAvailable: true,
        setTotpAvailable: (available: boolean) => ({ available }),
    }),
    reducers({
        dismissedReauthentication: [
            false,
            {
                setDismissedReauthentication: (_, { value }) => value,
                setTimeSensitiveAuthenticationRequired: () => false,
            },
        ],

        twoFactorRequired: [
            false,
            {
                setRequiresTwoFactor: (_, { value }) => value,
            },
        ],
        totpAvailable: [
            true as boolean,
            {
                setTotpAvailable: (_, { available }) => available,
            },
        ],
    }),

    loaders(({ values, actions }) => ({
        precheckResponse: [
            null as PrecheckResponseType | null,
            {
                precheck: async () => {
                    const response = await api.create('api/login/precheck', { email: values.user!.email })
                    return { status: 'completed', ...response }
                },
            },
        ],
        passkey2FA: [
            null as null,
            {
                beginPasskey2FA: async (_, breakpoint) => {
                    breakpoint()

                    // Step 1: Get authentication options from server
                    const beginResponse =
                        await api.create<PublicKeyCredentialRequestOptionsJSON>('api/login/2fa/passkey/begin/')

                    // Step 2: Use SimpleWebAuthn to get assertion from authenticator
                    const assertion = await startAuthentication({
                        optionsJSON: {
                            challenge: beginResponse.challenge,
                            timeout: beginResponse.timeout,
                            rpId: beginResponse.rpId,
                            allowCredentials: beginResponse.allowCredentials,
                            userVerification: beginResponse.userVerification as UserVerificationRequirement,
                        },
                    })

                    // Step 3: Send assertion to server to complete 2FA
                    await api.create('api/login/token', {
                        credential_id: assertion.id,
                        response: assertion.response,
                    })

                    return null
                },
            },
        ],
        passkeysAvailable: [
            false as boolean,
            {
                checkPasskeysAvailable: async () => {
                    try {
                        // Get available 2FA methods
                        const methods = await api.get<TwoFAMethodsResponse>('api/login/2fa/passkey/methods/')
                        // Store TOTP availability for UI
                        actions.setTotpAvailable(methods.has_totp)
                        return methods.has_passkeys
                    } catch {
                        // If it fails, assume no passkeys and TOTP might be available
                        actions.setTotpAvailable(true)
                        return false
                    }
                },
            },
        ],
    })),

    forms(({ actions, values }) => ({
        reauthentication: {
            defaults: {} as unknown as ReauthenticationForm,
            errors: ({ password, token }) => ({
                password: !password ? 'Please enter your password to continue' : undefined,
                token: values.twoFactorRequired && !token ? 'Please enter your 2FA code' : undefined,
            }),
            submit: async ({ password, token }, breakpoint): Promise<void> => {
                const email = userLogic.findMounted()?.values.user?.email
                await breakpoint(150)

                try {
                    if (!token) {
                        await api.create('api/login', { email, password })
                    } else {
                        await api.create('api/login/token', { token })
                    }
                } catch (e: unknown) {
                    if (e instanceof ApiError) {
                        if (e.code === '2fa_required') {
                            actions.setRequiresTwoFactor(true)
                            // Check for available 2FA methods when 2FA is required
                            actions.checkPasskeysAvailable()
                        }
                        if (e.code === 'invalid_credentials') {
                            actions.setReauthenticationManualErrors({ password: 'Incorrect password' })
                        }
                    }

                    throw e
                }
            },
        },
    })),

    selectors({
        showAuthenticationModal: [
            (s) => [s.timeSensitiveAuthenticationRequired, s.dismissedReauthentication],
            (timeSensitiveAuthenticationRequired, dismissedReauthentication): boolean => {
                return !!timeSensitiveAuthenticationRequired && !dismissedReauthentication
            },
        ],

        sensitiveSessionExpiresAt: [
            (s) => [s.user],
            (user): Dayjs => {
                return dayjs(user?.sensitive_session_expires_at)
            },
        ],
    }),

    subscriptions(({ values, actions }) => ({
        showAuthenticationModal: (shown) => {
            if (shown) {
                posthog.capture('reauthentication_modal_shown', {
                    interrupted_form: values.interruptedForm,
                })

                const modalTrackingLogic = modalInterruptionTrackingLogic.findMounted()
                if (modalTrackingLogic) {
                    modalTrackingLogic.actions.setInterruptedForm(null)
                }

                if (!values.precheckResponse) {
                    actions.precheck()
                }
            }
        },
    })),

    listeners(({ actions, values }) => ({
        submitReauthenticationSuccess: () => {
            if (Array.isArray(values.timeSensitiveAuthenticationRequired)) {
                values.timeSensitiveAuthenticationRequired[0]() // Resolve
            }
            posthog.capture('reauthentication_completed')
            actions.setTimeSensitiveAuthenticationRequired(false)
            // Refresh the user so we know the new session expiry
            actions.loadUser()
        },
        beginPasskey2FASuccess: () => {
            if (Array.isArray(values.timeSensitiveAuthenticationRequired)) {
                values.timeSensitiveAuthenticationRequired[0]() // Resolve
            }
            posthog.capture('reauthentication_completed', { method: 'passkey_2fa' })
            actions.setTimeSensitiveAuthenticationRequired(false)
            // Refresh the user so we know the new session expiry
            actions.loadUser()
        },
        submitReauthenticationFailure: () => {
            if (Array.isArray(values.timeSensitiveAuthenticationRequired)) {
                values.timeSensitiveAuthenticationRequired[1]() // Reject
            }
        },
        setDismissedReauthentication: ({ value }) => {
            if (value) {
                if (Array.isArray(values.timeSensitiveAuthenticationRequired)) {
                    values.timeSensitiveAuthenticationRequired[1]() // Reject
                }
                posthog.capture('reauthentication_modal_dismissed')
            }
        },
        checkReauthentication: () => {
            if (values.sensitiveSessionExpiresAt.diff(dayjs(), 'seconds') < LOOKAHEAD_EXPIRY_SECONDS) {
                // Here we try to offer a better UX by forcing re-authentication if they are about to timeout
                // which is nicer than when they try to do something later and get a 403.
                // We also make this a promise, so that `checkReauthentication` callsites can await
                // `asyncActions.checkReauthentication()` and proceed once re-authentication is completed
                return new Promise((resolve, reject) =>
                    actions.setTimeSensitiveAuthenticationRequired([resolve, reject])
                )
            }
        },
    })),
])
