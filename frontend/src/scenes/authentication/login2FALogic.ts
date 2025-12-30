import { type PublicKeyCredentialRequestOptionsJSON, startAuthentication } from '@simplewebauthn/browser'
import { actions, afterMount, connect, kea, listeners, path, reducers } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'

import api, { ApiError } from 'lib/api'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import type { login2FALogicType } from './login2FALogicType'
import { handleLoginRedirect } from './loginLogic'

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

export interface Passkey2FABeginResponse extends PublicKeyCredentialRequestOptionsJSON {}

export interface TwoFAMethodsResponse {
    has_totp: boolean
    has_passkeys: boolean
}

export interface LoginTokenResponse {
    success: boolean
}

const WEBAUTHN_ERROR_MESSAGES: Record<string, string> = {
    NotAllowedError: 'Authentication was cancelled or timed out.',
    SecurityError: 'Security error occurred. Please try again.',
    AbortError: 'Authentication was cancelled.',
}

interface WebAuthnError {
    name?: string
    detail?: string
}

function getPasskeyErrorMessage(error: unknown): string {
    if (error && typeof error === 'object' && 'name' in error) {
        const errorName = (error as WebAuthnError).name
        if (errorName && WEBAUTHN_ERROR_MESSAGES[errorName]) {
            return WEBAUTHN_ERROR_MESSAGES[errorName]
        }
    }

    if (error instanceof ApiError && error.detail) {
        return error.detail
    }

    return 'Passkey authentication failed. Please try again.'
}

export const login2FALogic = kea<login2FALogicType>([
    path(['scenes', 'authentication', 'login2FALogic']),
    connect(() => ({
        values: [preflightLogic, ['preflight'], featureFlagLogic, ['featureFlags']],
    })),
    actions({
        setGeneralError: (code: string, detail: string) => ({ code, detail }),
        setLoginStep: (step: LoginStep) => ({ step }),
        clearGeneralError: true,
        beginPasskey2FA: true,
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
    }),
    loaders(({ actions }) => ({
        passkey2FA: [
            null as null,
            {
                beginPasskey2FA: async (_, breakpoint) => {
                    breakpoint()
                    try {
                        // Step 1: Get authentication options from server
                        const beginResponse = await api.create<Passkey2FABeginResponse>('api/login/2fa/passkey/begin/')

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
                        actions.setGeneralError('passkey_error', getPasskeyErrorMessage(e))
                        throw e
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
    listeners({
        submitTwofactortokenSuccess: () => {
            handleLoginRedirect()
            // Reload the page after login to ensure POSTHOG_APP_CONTEXT is set correctly.
            window.location.reload()
        },
        beginPasskey2FASuccess: () => {
            handleLoginRedirect()
            // Reload the page after login to ensure POSTHOG_APP_CONTEXT is set correctly.
            window.location.reload()
        },
    }),
    afterMount(({ actions }) => {
        // Check if user has passkeys when component mounts
        actions.checkPasskeysAvailable()
    }),
])
