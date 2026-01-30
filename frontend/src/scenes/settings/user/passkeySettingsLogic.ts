import { type PublicKeyCredentialDescriptorJSON, startAuthentication, startRegistration } from '@simplewebauthn/browser'
import { actions, connect, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { twoFactorLogic } from 'scenes/authentication/twoFactorLogic'
import { userLogic } from 'scenes/userLogic'

import type { passkeySettingsLogicType } from './passkeySettingsLogicType'
import { getPasskeyErrorMessage } from './passkeys/utils'

export interface PasskeyCredential {
    id: number
    label: string
    created_at: string
    transports: string[]
    verified: boolean
    authenticator_type: 'platform' | 'hardware' | 'hybrid' | 'unknown'
}

export interface RegistrationBeginResponse {
    rp: { id: string; name: string }
    user: { id: string; name: string; displayName: string }
    challenge: string
    pubKeyCredParams: Array<{ type: 'public-key'; alg: number }>
    timeout: number
    excludeCredentials: PublicKeyCredentialDescriptorJSON[]
    authenticatorSelection: { residentKey: string; userVerification: string }
    attestation: string
    already_registered?: boolean
}

export interface RegistrationCompleteResponse {
    success: boolean
    message: string
    credential_id: string
}

export interface VerificationBeginResponse {
    challenge: string
    timeout: number
    rpId: string
    allowCredentials: PublicKeyCredentialDescriptorJSON[]
    userVerification: string
}

export type RegistrationStep = 'idle' | 'registering' | 'verifying' | 'complete'

export const passkeySettingsLogic = kea<passkeySettingsLogicType>([
    path(['scenes', 'settings', 'user', 'passkeySettingsLogic']),
    connect({
        actions: [userLogic, ['loadUser'], twoFactorLogic, ['loadStatus']],
    }),
    actions({
        beginRegistration: (label: string) => ({ label }),
        setRegistrationStep: (step: RegistrationStep) => ({ step }),
        setError: (error: string | null) => ({ error }),
        clearError: true,
        deletePasskey: (id: number) => ({ id }),
        renamePasskey: (id: number, label: string) => ({ id, label }),
        verifyPasskey: (id: number) => ({ id }),
        openDeleteModal: (id: number) => ({ id }),
        closeDeleteModal: true,
        openRenameModal: (id: number, currentLabel: string) => ({ id, currentLabel }),
        closeRenameModal: true,
    }),
    reducers({
        registrationStep: [
            'idle' as RegistrationStep,
            {
                setRegistrationStep: (_, { step }) => step,
                beginRegistration: () => 'registering',
            },
        ],
        registrationLabel: [
            '' as string,
            {
                beginRegistration: (_, { label }) => label,
                setRegistrationStep: (state, { step }) => (step === 'idle' ? '' : state),
            },
        ],
        error: [
            null as string | null,
            {
                setError: (_, { error }) => error,
                clearError: () => null,
                beginRegistration: () => null,
                verifyPasskeySuccess: () => null,
            },
        ],
        deleteModalId: [
            null as number | null,
            {
                openDeleteModal: (_, { id }) => id,
                closeDeleteModal: () => null,
                deletePasskeySuccess: () => null,
            },
        ],
        renameModal: [
            null as { id: number; currentLabel: string } | null,
            {
                openRenameModal: (_, { id, currentLabel }) => ({ id, currentLabel }),
                closeRenameModal: () => null,
                renamePasskeySuccess: () => null,
            },
        ],
        verifyingPasskeyId: [
            null as number | null,
            {
                verifyPasskey: (_, { id }) => id,
                verifyPasskeySuccess: () => null,
                verifyPasskeyFailure: () => null,
            },
        ],
    }),
    loaders(({ actions, values }) => ({
        passkeys: [
            [] as PasskeyCredential[],
            {
                loadPasskeys: async () => {
                    const response = await api.get<PasskeyCredential[]>('api/webauthn/credentials/')
                    return response
                },
                deletePasskey: async ({ id }) => {
                    await api.delete(`api/webauthn/credentials/${id}/`)
                    lemonToast.success('Passkey deleted')
                    return values.passkeys.filter((p: PasskeyCredential) => p.id !== id)
                },
                renamePasskey: async ({ id, label }) => {
                    const updated = await api.update<PasskeyCredential>(`api/webauthn/credentials/${id}/`, { label })
                    lemonToast.success('Passkey renamed')
                    return values.passkeys.map((p: PasskeyCredential) => (p.id === id ? updated : p))
                },
                verifyPasskey: async ({ id }) => {
                    try {
                        // Step 1: Begin verification
                        const verifyResponse = await api.create<VerificationBeginResponse>(
                            `api/webauthn/credentials/${id}/verify`
                        )

                        // Step 2: Verify with authenticator
                        const assertion = await startAuthentication({
                            optionsJSON: {
                                challenge: verifyResponse.challenge,
                                timeout: verifyResponse.timeout,
                                rpId: verifyResponse.rpId,
                                allowCredentials: verifyResponse.allowCredentials,
                                userVerification: verifyResponse.userVerification as UserVerificationRequirement,
                            },
                        })

                        // Step 3: Complete verification
                        const updated = await api.create<PasskeyCredential>(
                            `api/webauthn/credentials/${id}/verify_complete`,
                            assertion
                        )

                        lemonToast.success('Passkey verified successfully!')
                        return values.passkeys.map((p: PasskeyCredential) => (p.id === id ? updated : p))
                    } catch (e: any) {
                        actions.setError(getPasskeyErrorMessage(e, 'Failed to verify passkey. Please try again.'))
                        throw e
                    }
                },
            },
        ],
        registerPasskey: [
            null as null,
            {
                beginRegistration: async ({ label }) => {
                    try {
                        // Step 1: Get registration options
                        const beginResponse = await api.create<RegistrationBeginResponse>('api/webauthn/register/begin')

                        // Step 2: Create credential with authenticator
                        const attestation = await startRegistration({
                            optionsJSON: {
                                rp: beginResponse.rp,
                                user: beginResponse.user,
                                challenge: beginResponse.challenge,
                                pubKeyCredParams: beginResponse.pubKeyCredParams as PublicKeyCredentialParameters[],
                                timeout: beginResponse.timeout,
                                excludeCredentials: beginResponse.excludeCredentials,
                                authenticatorSelection:
                                    beginResponse.authenticatorSelection as AuthenticatorSelectionCriteria,
                                attestation: beginResponse.attestation as AttestationConveyancePreference,
                            },
                        })

                        // Step 3: Send attestation to server
                        const { credential_id: credentialId } = await api.create<RegistrationCompleteResponse>(
                            'api/webauthn/register/complete',
                            {
                                ...attestation,
                                label,
                            }
                        )

                        // Load passkeys so the new passkey appears in the list even if verification fails
                        actions.loadPasskeys()

                        // Step 4: Begin verification
                        actions.setRegistrationStep('verifying')

                        const verifyResponse = await api.create<VerificationBeginResponse>(
                            `api/webauthn/credentials/${credentialId}/verify`
                        )

                        // Step 5: Verify with authenticator
                        const assertion = await startAuthentication({
                            optionsJSON: {
                                challenge: verifyResponse.challenge,
                                timeout: verifyResponse.timeout,
                                rpId: verifyResponse.rpId,
                                allowCredentials: verifyResponse.allowCredentials,
                                userVerification: verifyResponse.userVerification as UserVerificationRequirement,
                            },
                        })

                        // Step 6: Complete verification
                        await api.create(`api/webauthn/credentials/${credentialId}/verify_complete`, assertion)

                        actions.setRegistrationStep('complete')
                        lemonToast.success('Passkey added successfully!')
                        actions.loadPasskeys()
                        actions.loadUser()
                        actions.loadStatus()

                        return null
                    } catch (e: any) {
                        actions.setRegistrationStep('idle')
                        actions.setError(getPasskeyErrorMessage(e, 'Failed to register passkey. Please try again.'))
                        // Load passkeys in case the passkey was created but verification failed
                        actions.loadPasskeys()
                        throw e
                    }
                },
            },
        ],
    })),
    listeners(({ actions }) => ({
        deletePasskeySuccess: () => {
            actions.loadUser()
            actions.loadStatus()
        },
        verifyPasskeySuccess: () => {
            actions.loadUser()
            actions.loadStatus()
        },
    })),
])
