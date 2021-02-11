import { kea } from 'kea'
import api from 'lib/api'
import { toast } from 'react-toastify'
import { PrevalidatedInvite } from '~/types'
import { inviteSignupLogicType } from './inviteSignupLogicType'

export enum ErrorCodes {
    InvalidInvite = 'invalidInvite',
    InvalidRecipient = 'invalidRecepient',
    Unknown = 'unknown',
}

interface ErrorInterface {
    code: ErrorCodes
    detail?: string
}

export const inviteSignupLogic = kea<inviteSignupLogicType<PrevalidatedInvite, ErrorInterface>>({
    actions: {
        setError: (payload: ErrorInterface) => ({ payload }),
        setInviteId: (id: string) => ({ id }),
        prevalidateInvite: true,
    },
    reducers: {
        error: [
            null as ErrorInterface | null,
            {
                setError: (_, { payload }) => payload,
            },
        ],
        inviteId: [
            null as null | string,
            {
                setInviteId: (_, { id }) => id,
            },
        ],
    },
    loaders: ({ actions, values }) => ({
        invite: [
            null as PrevalidatedInvite | null,
            {
                prevalidateInvite: async (_, breakpoint) => {
                    breakpoint()

                    try {
                        return await api.get(`api/signup/${values.inviteId}/`)
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
                acceptInvite: async (_, breakpoint) => {
                    breakpoint()

                    if (!values.inviteId) {
                        return null
                    }

                    return await api.create(`api/signup/${values.inviteId}/`, {})
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
        '/signup/*': ({ _: id }: { _: string }) => {
            actions.setInviteId(id)
            actions.prevalidateInvite()
        },
    }),
})
