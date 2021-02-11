import { kea } from 'kea'
import api from 'lib/api'
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
    },
    reducers: {
        error: [
            null as ErrorInterface | null,
            {
                setError: (_, { payload }) => payload,
            },
        ],
    },
    loaders: ({ actions }) => ({
        invite: [
            null as PrevalidatedInvite | null,
            {
                prevalidateInvite: async (id: string) => {
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
    }),
    urlToAction: ({ actions }) => ({
        '/signup/*': ({ _: id }: { _: string }) => {
            actions.prevalidateInvite(id)
        },
    }),
})
