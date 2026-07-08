import { type PublicKeyCredentialRequestOptionsJSON, startAuthentication } from '@simplewebauthn/browser'
import { actions, afterMount, connect, kea, listeners, path, reducers } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'

import api, { ApiError } from 'lib/api'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { handleLoginRedirect } from 'scenes/authentication/login/loginLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { getPasskeyErrorMessage, isWebAuthnCancellation } from 'scenes/settings/user/passkeys/utils'

import type { login2FALogicType } from './login2FALogicType'

export interface AuthenticateResponseType {
    success: boolean
    errorCode?: string
    errorDetail?: string
}

export interface TwoFactorForm {
    token: string
}

export enum LoginStep {
    LOGIN = 'login',
    TWO_FACTOR = 'two_factor',
}

export interface TwoFAMethodsResponse {
    has_totp: boolean
    has_passkeys: boolean
}

export interface LoginTokenResponse {
    success: boolean
}

export interface TwoFactorResetRequestResponse {
    success: boolean
    error?: string
    requires_login?: boolean
}

export const login2FALogic = kea<login2FALogicType>([
    path(['scenes', 'authentication', 'login-2fa', 'login2FALogic']),
    connect(() => ({
        values: [preflightLogic, ['preflight'], featureFlagLogic, ['featureFlags']],
    })),
    actions({
        setGeneralError: (code: string, detail: string) => ({ code, detail }),
        setLoginStep: (step: LoginStep) => ({ step }),
        clearGeneralError: true,
        beginPasskey2FA: true,
        passkey2FACancelled: true,
        checkPasskeysAvailable: true,
        setTotpAvailable: (available: boolean) => ({ available }),
    }),
    reducers({
        generalError: [
            null as { code: string; detail: string } | null,
            {
                setGeneralError: (_, error) => error,
                clearGeneralError: () => null,
            },
        ],
        totpAvailable: [
            true as boolean,
            {
                setTotpAvailable: (_, { available }) => available,
            },
        ],
        passkey2FAWasCancelled: [
            false,
            {
                beginPasskey2FA: () => false,
                passkey2FACancelled: () => true,
            },
        ],
    }),
    loaders(({ actions }) => ({
        passkey2FA: [
            null as null,
            {
                beginPasskey2FA: async (_, breakpoint) => {
                    breakpoint()
                    try {
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
                                userVerification: beginResponse.userVerification,
                            },
                        })

                        // Step 3: Send assertion to server to complete 2FA
                        await api.create<LoginTokenResponse>('api/login/token', {
                            credential_id: assertion.id,
                            response: assertion.response,
                        })

                        return null
                    } catch (e: unknown) {
                        if (isWebAuthnCancellation(e)) {
                            // Expected user cancellation — fully swallow so it
                            // doesn't surface in the UI or in error tracking.
                            actions.passkey2FACancelled()
                            return null
                        }
                        actions.setGeneralError('passkey_error', getPasskeyErrorMessage(e))
                        throw e
                    }
                },
            },
        ],
        twoFactorResetRequest: [
            null as TwoFactorResetRequestResponse | null,
            {
                requestTwoFactorReset: async () => {
                    try {
                        return await api.create<TwoFactorResetRequestResponse>('api/reset_2fa/request/')
                    } catch (e: unknown) {
                        if (e instanceof ApiError) {
                            return {
                                success: false,
                                error:
                                    e.data?.error ||
                                    e.detail ||
                                    'Could not send a reset email. Please try again later.',
                                requires_login: e.data?.requires_login === true,
                            }
                        }
                        return { success: false, error: 'Could not send a reset email. Please try again later.' }
                    }
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
    forms(({ actions }) => ({
        twofactortoken: {
            defaults: { token: '' } as TwoFactorForm,
            errors: ({ token }) => ({
                token: !token ? 'Please enter a token to continue' : null,
            }),
            submit: async ({ token }, breakpoint) => {
                breakpoint()
                try {
                    await api.create<LoginTokenResponse>('api/login/token', { token })
                } catch (e: unknown) {
                    if (e instanceof ApiError) {
                        actions.setGeneralError(e.code || 'unknown_error', e.detail || 'An error occurred')
                    } else {
                        actions.setGeneralError('unknown_error', 'An unexpected error occurred')
                    }
                    throw e
                }
            },
        },
    })),
    listeners(({ values }) => ({
        submitTwofactortokenSuccess: () => {
            handleLoginRedirect()
            // Reload the page after login to ensure POSTHOG_APP_CONTEXT is set correctly.
            window.location.reload()
        },
        beginPasskey2FASuccess: () => {
            // The loader returns null on user cancellation to avoid surfacing
            // the DOMException to global error capture. Skip the post-login
            // redirect/reload path in that case so the user stays on the
            // 2FA screen and can retry.
            if (values.passkey2FAWasCancelled) {
                return
            }
            handleLoginRedirect()
            // Reload the page after login to ensure POSTHOG_APP_CONTEXT is set correctly.
            window.location.reload()
        },
    })),
    afterMount(({ actions }) => {
        // Check if user has passkeys when component mounts
        actions.checkPasskeysAvailable()
    }),
])
