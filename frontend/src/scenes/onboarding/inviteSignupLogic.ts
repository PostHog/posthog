import { kea } from 'kea'
import api from 'lib/api'
import { PrevalidatedInvite } from '~/types'
import { inviteSignupLogicType } from './inviteSignupLogicType'

export enum ErrorCodes {
    InvalidInvite = 'invalidInvite',
    Unknown = 'unknown',
}

type ErrorType = ErrorCodes | null

export const inviteSignupLogic = kea<inviteSignupLogicType<PrevalidatedInvite, ErrorType>>({
    actions: {
        setError: (errorCode: ErrorType) => ({ errorCode }),
    },
    reducers: {
        error: [
            null as ErrorType,
            {
                setError: (_, { errorCode }) => errorCode,
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
                            actions.setError(ErrorCodes.InvalidInvite)
                        } else {
                            actions.setError(ErrorCodes.Unknown)
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
