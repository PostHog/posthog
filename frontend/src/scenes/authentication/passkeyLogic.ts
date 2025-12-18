import { type PublicKeyCredentialDescriptorJSON, startAuthentication } from '@simplewebauthn/browser'
import { actions, connect, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import api from 'lib/api'
import { apiStatusLogic } from 'lib/logic/apiStatusLogic'
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
const WEBAUTHN_ERROR_MESSAGES: Record<string, string> = {
    NotAllowedError: 'Authentication was cancelled or timed out.',
    SecurityError: 'Security error occurred. Please try again.',
    AbortError: 'Authentication was cancelled.',
}

function getPasskeyErrorMessage(error: any): string {
    if (error?.name && WEBAUTHN_ERROR_MESSAGES[error.name]) {
        return WEBAUTHN_ERROR_MESSAGES[error.name]
    }

    return error?.detail || 'Passkey authentication failed. Please try again.'
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
                    } catch (e: any) {
                        actions.setGeneralError('passkey_error', getPasskeyErrorMessage(e))
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
    })),
])
