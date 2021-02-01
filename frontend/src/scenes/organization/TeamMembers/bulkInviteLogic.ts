import { kea } from 'kea'
import { bulkInviteLogicType } from './bulkInviteLogicType'
import { OrganizationInviteType } from '~/types'
import api from 'lib/api'
import { toast } from 'react-toastify'

interface InviteType {
    email: string
    first_name?: string
    isValid: boolean
}

interface BulkInviteResponse {
    invites: OrganizationInviteType[]
}

const DEFAULT_INVITE = { email: '', first_name: '', isValid: true }
const DEFAULT_INVITES = [DEFAULT_INVITE, DEFAULT_INVITE, DEFAULT_INVITE]

export const bulkInviteLogic = kea<bulkInviteLogicType<BulkInviteResponse, InviteType>>({
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
    loaders: ({ values }) => ({
        invitedTeamMembers: [
            { invites: [] } as BulkInviteResponse,
            {
                inviteTeamMembers: async () => {
                    if (!values.canSubmit) {
                        return []
                    }
                    const payload: Record<
                        'invites',
                        Record<'target_email' | 'first_name', string | null | undefined>[]
                    > = { invites: [] }
                    for (const invite of values.invites) {
                        if (!invite.email) {
                            continue
                        }
                        payload.invites.push({ target_email: invite.email, first_name: invite.first_name })
                    }
                    return await api.create('api/organizations/@current/invites/bulk/', payload)
                },
            },
        ],
    }),
    listeners: ({ values }) => ({
        inviteTeamMembersSuccess: (): void => {
            toast.success(`Invites sent to ${values.invitedTeamMembers.invites.length} new team members.`)
        },
    }),
})
