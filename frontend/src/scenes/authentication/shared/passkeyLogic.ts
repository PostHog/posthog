import {
    browserSupportsWebAuthnAutofill,
    type PublicKeyCredentialDescriptorJSON,
    startAuthentication,
} from '@simplewebauthn/browser'
import { actions, connect, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import api from 'lib/api'
import { apiStatusLogic } from 'lib/logic/apiStatusLogic'
import { isWebKitBrowser } from 'lib/utils/dom'
import { handleLoginRedirect, loginLogic } from 'scenes/authentication/login/loginLogic'
import { getPasskeyErrorMessage, isWebAuthnCancellation } from 'scenes/settings/user/passkeys/utils'
import { userLogic } from 'scenes/userLogic'

import type { passkeyLogicType } from './passkeyLogicType'

export interface PasskeyLoginBeginResponse {
    challenge: string
    timeout: number
    rpId: string
    allowCredentials: PublicKeyCredentialDescriptorJSON[]
    userVerification: string
}

export interface BeginPasskeyLoginParams {
    next?: string
    email?: string
    reauth?: 'true' | 'false'
}

export const passkeyLogic = kea<passkeyLogicType>([
    path(['scenes', 'authentication', 'shared', 'passkeyLogic']),
    connect(() => ({
        actions: [
            loginLogic,
            ['setGeneralError'],
            apiStatusLogic,
            ['setTimeSensitiveAuthenticationRequired'],
            userLogic,
            ['loadUser'],
        ],
    })),
    actions({
        beginPasskeyLogin: (
            allowCredentials?: PublicKeyCredentialDescriptorJSON[],
            params?: BeginPasskeyLoginParams
        ) => ({ allowCredentials, params }),
        startPasskeyAuthentication: true,
        startConditionalPasskeyLogin: true,
        passkeyAuthenticationCancelled: true,
        reset: true,
    }),
    reducers({
        allowCredentialsFromPrecheck: [
            [] as PublicKeyCredentialDescriptorJSON[],
            {
                beginPasskeyLogin: (state, { allowCredentials }) => allowCredentials ?? state,
                reset: () => [],
            },
        ],
        redirectLink: [
            undefined as string | undefined,
            {
                beginPasskeyLogin: (state, { params }) => params?.next ?? state,
            },
        ],
        isReauth: [
            false,
            {
                beginPasskeyLogin: (_, { params }) => params?.reauth === 'true',
                reset: () => false,
            },
        ],
        isLoading: [
            false,
            {
                beginPasskeyLogin: () => true,
                startPasskeyAuthenticationSuccess: () => false,
                startPasskeyAuthenticationFailure: () => false,
                reset: () => false,
            },
        ],
        wasCancelled: [
            false,
            {
                beginPasskeyLogin: () => false,
                passkeyAuthenticationCancelled: () => true,
            },
        ],
    }),
    loaders(({ values, actions }) => ({
        loginWithPasskey: [
            null as null,
            {
                startPasskeyAuthentication: async () => {
                    try {
                        // Step 1: Get authentication options from server
                        const beginResponse = await api.create<PasskeyLoginBeginResponse>('api/webauthn/login/begin/')

                        // Step 2: Use SimpleWebAuthn to get assertion from authenticator
                        // Use provided allowCredentials if available (from precheck), otherwise use server response
                        const precheckCredentials = values.allowCredentialsFromPrecheck ?? []
                        const credentialsToUse =
                            precheckCredentials.length > 0 ? precheckCredentials : beginResponse.allowCredentials

                        const assertion = await startAuthentication({
                            optionsJSON: {
                                challenge: beginResponse.challenge,
                                timeout: beginResponse.timeout,
                                rpId: beginResponse.rpId,
                                allowCredentials: credentialsToUse,
                                userVerification: beginResponse.userVerification as UserVerificationRequirement,
                            },
                        })

                        // Step 3: Send assertion to server to complete login
                        await api.create('api/webauthn/login/complete/', assertion)

                        return null
                    } catch (e: unknown) {
                        if (isWebAuthnCancellation(e)) {
                            // Expected user cancellation — fully swallow so it
                            // doesn't surface in the UI or in error tracking.
                            actions.passkeyAuthenticationCancelled()
                            return null
                        }
                        actions.setGeneralError('passkey_error', getPasskeyErrorMessage(e))
                        throw e
                    }
                },
            },
        ],
    })),
    listeners(({ actions, values, cache }) => ({
        beginPasskeyLogin: () => {
            // Don't start a second passkey sign-in while one is already in flight (e.g. a
            // double-clicked passkey button) — concurrent WebAuthn requests hang WebKit.
            if (values.loginWithPasskeyLoading) {
                return
            }
            // After setting credentials in reducer, start the authentication
            actions.startPasskeyAuthentication()
        },
        startConditionalPasskeyLogin: async () => {
            // WebKit-only. Safari/iOS freeze on the auto-modal, so there we offer passkeys via the
            // email field's autofill instead
            if (!isWebKitBrowser()) {
                return
            }
            // Latch synchronously before the first await so a repeat trigger can't race past the guard.
            if (cache.passkeyAutofillStarted) {
                return
            }
            cache.passkeyAutofillStarted = true
            if (!(await browserSupportsWebAuthnAutofill())) {
                return
            }
            try {
                const beginResponse = await api.create<PasskeyLoginBeginResponse>('api/webauthn/login/begin/')
                const assertion = await startAuthentication({
                    optionsJSON: {
                        challenge: beginResponse.challenge,
                        timeout: beginResponse.timeout,
                        rpId: beginResponse.rpId,
                        // Conditional UI must not constrain credentials — the browser offers whatever
                        // discoverable passkeys exist for this site.
                        allowCredentials: [],
                        userVerification: beginResponse.userVerification as UserVerificationRequirement,
                    },
                    useBrowserAutofill: true,
                })
                await api.create('api/webauthn/login/complete/', assertion)
                handleLoginRedirect()
                window.location.reload()
            } catch (e: unknown) {
                // The autofill passkey prompt is routinely dismissed — the user types a password
                // instead, or navigates away. Swallow those; surface anything genuinely wrong.
                if (!isWebAuthnCancellation(e)) {
                    actions.setGeneralError('passkey_error', getPasskeyErrorMessage(e))
                }
            }
        },
        startPasskeyAuthenticationSuccess: async () => {
            // The loader returns null on user cancellation to avoid surfacing
            // the DOMException to global error capture. Skip the post-login
            // redirect/reload path in that case so the user stays on the
            // login screen and can retry.
            if (values.wasCancelled) {
                actions.reset()
                return
            }
            // for reauth, clear authentication required flag
            if (values.isReauth) {
                actions.setTimeSensitiveAuthenticationRequired(false)
                actions.loadUser()
                actions.reset()
                return
            }

            // For regular login, redirect and reload
            if (values.redirectLink) {
                router.actions.push(values.redirectLink)
            } else {
                handleLoginRedirect()
            }

            window.location.reload()
        },
        startPasskeyAuthenticationFailure: () => {
            // Reset state on real authentication failures so the user can fall
            // back to the normal login flow (e.g., password + 2FA).
            actions.reset()
        },
    })),
])
