import { kea } from 'kea'
import api from 'lib/api'
import { lemonToast } from 'lib/components/lemonToast'
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
    email_opt_in: boolean
}

export const inviteSignupLogic = kea<inviteSignupLogicType>({
    path: ['scenes', 'authentication', 'inviteSignupLogic'],
    actions: {
        setError: (payload: ErrorInterface) => ({ payload }),
    },
    reducers: {
        error: [
            null as ErrorInterface | null,
            {
                setError: (_, { payload }) => payload,
            },
        ],
    },
    loaders: ({ actions, values }) => ({
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
    }),
    listeners: ({ values }) => ({
        acceptInviteSuccess: async (_, breakpoint) => {
            lemonToast.success(`You have joined ${values.invite?.organization_name}! Taking you to PostHog now…`)
            await breakpoint(2000) // timeout for the user to read the toast
            window.location.href = '/' // hard refresh because the current_organization changed
        },
    }),
    urlToAction: ({ actions }) => ({
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
    }),
})
