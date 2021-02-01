import { kea } from 'kea'
import { bulkInviteLogicType } from './bulkInviteLogicType'

export interface InviteType {
    email: string
    name?: string
    isValid: boolean
}

const DEFAULT_INVITE = { email: '', name: '', isValid: false }
const DEFAULT_INVITES = [DEFAULT_INVITE, DEFAULT_INVITE, DEFAULT_INVITE]

export const bulkInviteLogic = kea<bulkInviteLogicType>({
    actions: {
        setInviteAtIndex: (payload, index) => ({ payload, index }),
        addMoreInvites: true,
        resetInvites: true,
    },
    reducers: {
        invites: [
            DEFAULT_INVITES as InviteType[],
            {
                setInviteAtIndex: (state, { payload, index }) => {
                    state[index] = payload
                    return state
                },
                addMoreInvites: (state) => {
                    return [...state, DEFAULT_INVITE, DEFAULT_INVITE]
                },
                resetInvites: () => DEFAULT_INVITES,
            },
        ],
    },
})
