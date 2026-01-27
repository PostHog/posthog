import { startRegistration } from '@simplewebauthn/browser'
import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { urlToAction } from 'kea-router'
import posthog from 'posthog-js'

import api from 'lib/api'
import { ValidatedPasswordResult, validatePassword } from 'lib/components/PasswordStrength'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { getPasskeyErrorMessage } from 'scenes/settings/user/passkeys/utils'

import { PrevalidatedInvite } from '~/types'

import type { RegistrationBeginResponse } from '../settings/user/passkeySettingsLogic'
import type { inviteSignupLogicType } from './inviteSignupLogicType'

export enum ErrorCodes {
    InvalidInvite = 'invalid_invite',
    InvalidRecipient = 'invalid_recipient',
    Unknown = 'unknown',
}

export interface ErrorInterface {
    code: ErrorCodes
    detail?: string
}

export interface AcceptInvitePayloadInterface {
    first_name?: string
    password?: string
    role_at_organization?: string
}

export const inviteSignupLogic = kea<inviteSignupLogicType>([
    path(['scenes', 'authentication', 'inviteSignupLogic']),
    connect(() => ({
        values: [featureFlagLogic, ['featureFlags']],
    })),
    actions({
        setError: (payload: ErrorInterface) => ({ payload }),
        registerPasskey: true,
        setPasskeyRegistered: (registered: boolean) => ({ registered }),
        setPasskeyRegistering: (registering: boolean) => ({ registering }),
        setPasskeyError: (error: string | null) => ({ error }),
    }),
    reducers({
        error: [
            null as ErrorInterface | null,
            {
                setError: (_, { payload }) => payload,
            },
        ],
        passkeyRegistered: [
            false,
            {
                setPasskeyRegistered: (_, { registered }) => registered,
            },
        ],
        isPasskeyRegistering: [
            false,
            {
                setPasskeyRegistering: (_, { registering }) => registering,
            },
        ],
        passkeyError: [
            null as string | null,
            {
                setPasskeyError: (_, { error }) => error,
                registerPasskey: () => null,
            },
        ],
    }),
    loaders(({ actions, values }) => ({
        invite: [
            null as PrevalidatedInvite | null,
            {
                prevalidateInvite: async (id: string, breakpoint) => {
                    breakpoint()

                    try {
                        return await api.get(`api/signup/${id}/`)
                    } catch (e: any) {
                        if (e.status === 400) {
                            if (e.code === 'invalid_recipient') {
                                actions.setError({ code: ErrorCodes.InvalidRecipient, detail: e.detail })
                            } else if (e.code === 'account_exists') {
                                location.href = e.detail
                            } else {
                                actions.setError({ code: ErrorCodes.InvalidInvite, detail: e.detail })
                            }
                        } else {
                            actions.setError({ code: ErrorCodes.Unknown })
                        }
                        return null
                    }
                },
            },
        ],
        acceptedInvite: [
            null,
            {
                acceptInvite: async (payload?: AcceptInvitePayloadInterface, breakpoint?) => {
                    breakpoint()
                    if (!values.invite) {
                        return null
                    }
                    return await api.create(`api/signup/${values.invite.id}/`, payload)
                },
            },
        ],
    })),
    forms(({ actions, values }) => ({
        signup: {
            defaults: { role_at_organization: '' } as AcceptInvitePayloadInterface,
            errors: ({ password, first_name, role_at_organization }) => ({
                password:
                    !values.passkeyRegistered && !password
                        ? 'Please enter your password to continue'
                        : !values.passkeyRegistered
                          ? values.validatedPassword.feedback || undefined
                          : undefined,
                first_name: !first_name ? 'Please enter your name' : undefined,
                role_at_organization: !role_at_organization ? 'Please select your role to continue' : undefined,
            }),
            submit: async (payload, breakpoint) => {
                breakpoint()

                if (!values.invite) {
                    return
                }

                try {
                    const submitPayload = { ...payload }
                    if (values.passkeyRegistered) {
                        delete submitPayload.password
                    }

                    const res = await api.create(`api/signup/${values.invite.id}/`, submitPayload)
                    location.href = res.redirect_url || '/' // hard refresh because the current_organization changed
                } catch (e) {
                    posthog.captureException(e)
                    actions.setSignupManualErrors({
                        generic: {
                            code: (e as Record<string, any>).code,
                            detail: (e as Record<string, any>).detail,
                        },
                    })
                    throw e
                }
            },
        },
    })),
    selectors({
        validatedPassword: [
            (s) => [s.signup],
            ({ password }): ValidatedPasswordResult => {
                return validatePassword(password)
            },
        ],
        passkeySignupEnabled: [
            (s) => [s.featureFlags],
            (featureFlags): boolean => {
                return !!featureFlags[FEATURE_FLAGS.PASSKEY_SIGNUP_ENABLED]
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        prevalidateInviteSuccess: ({ invite }) => {
            if (invite?.first_name) {
                actions.setSignupValue('first_name', invite.first_name)
            }
        },
        setPasskeyRegistered: ({ registered }) => {
            if (registered) {
                actions.setSignupValue('password', '')
            }
        },
        registerPasskey: async () => {
            const email = values.invite?.target_email
            if (!email) {
                actions.setPasskeyError('Email is required')
                return
            }

            actions.setPasskeyRegistering(true)
            actions.setPasskeyError(null)

            try {
                const beginResponse = await api.create<RegistrationBeginResponse>(
                    'api/webauthn/signup-register/begin/',
                    { email }
                )

                if (beginResponse.already_registered) {
                    actions.setPasskeyRegistered(true)
                    actions.setSignupValue('password', '')
                    return
                }

                const attestation = await startRegistration({
                    optionsJSON: {
                        rp: beginResponse.rp,
                        user: beginResponse.user,
                        challenge: beginResponse.challenge,
                        pubKeyCredParams: beginResponse.pubKeyCredParams as PublicKeyCredentialParameters[],
                        timeout: beginResponse.timeout,
                        excludeCredentials: beginResponse.excludeCredentials ?? [],
                        authenticatorSelection: beginResponse.authenticatorSelection as AuthenticatorSelectionCriteria,
                        attestation: beginResponse.attestation as AttestationConveyancePreference,
                    },
                })

                await api.create('api/webauthn/signup-register/complete/', attestation)

                actions.setPasskeyRegistered(true)
                actions.setSignupValue('password', '')
            } catch (e: any) {
                actions.setPasskeyError(getPasskeyErrorMessage(e, 'Failed to register passkey. Please try again.'))
            } finally {
                actions.setPasskeyRegistering(false)
            }
        },
    })),
    urlToAction(({ actions }) => ({
        '/signup/*': ({ _: id }, { error_code, error_detail }) => {
            if (error_code) {
                if ((Object.values(ErrorCodes) as string[]).includes(error_code)) {
                    actions.setError({ code: error_code as ErrorCodes, detail: error_detail })
                } else {
                    actions.setError({ code: ErrorCodes.Unknown, detail: error_detail })
                }
            } else if (id) {
                actions.prevalidateInvite(id)
            }
        },
    })),
])
