import { kea } from 'kea'
import api from 'lib/api'
import { toast } from 'react-toastify'
import { PrevalidatedInvite } from '~/types'
import { inviteSignupLogicType } from './inviteSignupLogicType'

export enum ErrorCodes {
    InvalidInvite = 'invalid_invite',
    InvalidRecipient = 'invalid_recipient',
    Unknown = 'unknown',
}

interface ErrorInterface {
    code: ErrorCodes
    detail?: string
}

interface AcceptInvitePayloadInterface {
    first_name?: string
    password: string
    email_opt_in: boolean
}

export const inviteSignupLogic = kea<
    inviteSignupLogicType<PrevalidatedInvite, ErrorInterface, AcceptInvitePayloadInterface>
>({
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
                    } catch (e) {
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
            toast.success(`You have joined ${values.invite?.organization_name}! Taking you to PostHog now...`)
            await breakpoint(2000) // timeout for the user to read the toast
            window.location.href = '/' // hard refresh because the current_organization changed
        },
    }),
    urlToAction: ({ actions }) => ({
        '/signup/*': (
            { _: id }: { _: string },
            { error_code, error_detail }: { error_code?: string; error_detail?: string }
        ) => {
            if (error_code) {
                if ((Object.values(ErrorCodes) as string[]).includes(error_code)) {
                    actions.setError({ code: error_code as ErrorCodes, detail: error_detail })
                } else {
                    actions.setError({ code: ErrorCodes.Unknown, detail: error_detail })
                }
            } else {
                actions.prevalidateInvite(id)
            }
        },
    }),
})
