import {
    type PublicKeyCredentialDescriptorJSON,
    type WebAuthnError,
    startAuthentication,
} from '@simplewebauthn/browser'
import { actions, connect, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import api from 'lib/api'
import { apiStatusLogic } from 'lib/logic/apiStatusLogic'
import { getPasskeyErrorMessage } from 'scenes/settings/user/passkeys/utils'
import { userLogic } from 'scenes/userLogic'

import { handleLoginRedirect, loginLogic } from './loginLogic'
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

function extractWebAuthnErrorName(e: unknown): string | undefined {
    if (e && typeof e === 'object' && 'name' in e && typeof (e as WebAuthnError).name === 'string') {
        return (e as WebAuthnError).name
    }
    if (e && typeof e === 'object' && 'error' in e) {
        const nested = (e as { error?: WebAuthnError }).error
        if (nested?.name) {
            return nested.name
        }
    }
    return undefined
}

export const passkeyLogic = kea<passkeyLogicType>([
    path(['scenes', 'authentication', 'passkeyLogic']),
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
    }),
    loaders(({ values, actions }) => ({
        loginWithPasskey: [
            null as null,
            {
                startPasskeyAuthentication: async () => {
                    posthog.capture('passkey login started', { reauth: values.isReauth })

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

                        posthog.capture('passkey login succeeded', { reauth: values.isReauth })

                        return null
                    } catch (e: unknown) {
                        const errorName = extractWebAuthnErrorName(e)
                        const userCancelled = errorName === 'NotAllowedError' || errorName === 'AbortError'
                        posthog.capture('passkey login failed', {
                            error_name: errorName,
                            error_code: (e as { code?: string })?.code,
                            error_status: (e as { status?: number })?.status,
                            error_message: getPasskeyErrorMessage(e),
                            user_cancelled: userCancelled,
                            reauth: values.isReauth,
                        })

                        // Only set error if it's not a user cancellation (those are expected)
                        if (!userCancelled) {
                            actions.setGeneralError('passkey_error', getPasskeyErrorMessage(e))
                        }
                        throw e
                    }
                },
            },
        ],
    })),
    listeners(({ actions, values }) => ({
        beginPasskeyLogin: () => {
            // After setting credentials in reducer, start the authentication
            actions.startPasskeyAuthentication()
        },
        startPasskeyAuthenticationSuccess: async () => {
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
            // When passkey authentication fails (user cancels, etc.), reset state
            // This allows the normal login flow to continue (e.g., password + 2FA)
            actions.reset()
        },
    })),
])
