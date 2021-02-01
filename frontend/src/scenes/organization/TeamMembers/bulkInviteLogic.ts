import { kea } from 'kea'
import { bulkInviteLogicType } from './bulkInviteLogicType'

interface InviteType {
    email: string
    first_name?: string
    isValid: boolean
}

const DEFAULT_INVITE = { email: '', first_name: '', isValid: true }
const DEFAULT_INVITES = [DEFAULT_INVITE, DEFAULT_INVITE, DEFAULT_INVITE]

export const bulkInviteLogic = kea<bulkInviteLogicType>({
    actions: {
        updateInviteAtIndex: (payload, index: number) => ({ payload, index }),
        addMoreInvites: true,
        resetInvites: true,
    },
    reducers: {
        invites: [
            DEFAULT_INVITES as InviteType[],
            {
                updateInviteAtIndex: (state, { payload, index }) => {
                    const newState = [...state]
                    newState[index] = { ...state[index], ...payload }
                    return newState
                },
                addMoreInvites: (state) => {
                    return [...state, DEFAULT_INVITE, DEFAULT_INVITE]
                },
                resetInvites: () => DEFAULT_INVITES,
            },
        ],
    },
    selectors: {
        canSubmit: [
            (selectors) => [selectors.invites],
            (invites: InviteType[]) => {
                let atLeastOneValidEmail = false
                for (const invite of invites) {
                    if (!invite.isValid) {
                        return false
                    }
                    if (invite.email && invite.isValid) {
                        atLeastOneValidEmail = true
                    }
                }
                return atLeastOneValidEmail
            },
        ],
    },
})
