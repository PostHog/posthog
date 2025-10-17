import { actions, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { urlToAction } from 'kea-router'

import api from 'lib/api'
import { ValidatedPasswordResult, validatePassword } from 'lib/components/PasswordStrength'

import { PrevalidatedInvite } from '~/types'

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
    password: string
    role_at_organization?: string
}

export const inviteSignupLogic = kea<inviteSignupLogicType>([
    path(['scenes', 'authentication', 'inviteSignupLogic']),
    actions({
        setError: (payload: ErrorInterface) => ({ payload }),
    }),
    reducers({
        error: [
            null as ErrorInterface | null,
            {
                setError: (_, { payload }) => payload,
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
                password: !password
                    ? 'Please enter your password to continue'
                    : values.validatedPassword.feedback || undefined,
                first_name: !first_name ? 'Please enter your name' : undefined,
                role_at_organization: !role_at_organization ? 'Please select your role to continue' : undefined,
            }),
            submit: async (payload, breakpoint) => {
                breakpoint()

                if (!values.invite) {
                    return
                }

                try {
                    const res = await api.create(`api/signup/${values.invite.id}/`, payload)
                    location.href = res.redirect_url || '/' // hard refresh because the current_organization changed
                } catch (e) {
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
    }),
    listeners(({ actions }) => ({
        prevalidateInviteSuccess: ({ invite }) => {
            if (invite?.first_name) {
                actions.setSignupValue('first_name', invite.first_name)
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
