import { kea } from 'kea'
import { bulkInviteLogicType } from './bulkInviteLogicType'
import { OrganizationInviteType } from '~/types'
import api from 'lib/api'
import { toast } from 'react-toastify'
import { organizationLogic } from 'scenes/organizationLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

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
            (invites: InviteType[]) =>
                invites.filter(({ email }) => !!email).length > 0 &&
                invites.filter(({ isValid }) => !isValid).length == 0,
        ],
    },
    loaders: ({ values }) => ({
        invitedTeamMembers: [
            { invites: [] } as BulkInviteResponse,
            {
                inviteTeamMembers: async () => {
                    if (!values.canSubmit) {
                        return { invites: [] }
                    }

                    const payload = {
                        invites: [] as { target_email: string | null; first_name?: string | null }[],
                    }

                    for (const invite of values.invites) {
                        if (!invite.email) {
                            continue
                        }
                        payload.invites.push({ target_email: invite.email, first_name: invite.first_name })
                    }

                    eventUsageLogic.actions.reportBulkInviteAttempted(
                        payload.invites.length,
                        payload.invites.filter((invite) => !!invite.first_name).length
                    )

                    return await api.create('api/organizations/@current/invites/bulk/', payload)
                },
            },
        ],
    }),
    listeners: ({ values, actions }) => ({
        inviteTeamMembersSuccess: (): void => {
            toast.success(`Invites sent to ${values.invitedTeamMembers.invites.length} new team members.`)
            organizationLogic.actions.loadCurrentOrganization()
            actions.resetInvites()
        },
    }),
})
