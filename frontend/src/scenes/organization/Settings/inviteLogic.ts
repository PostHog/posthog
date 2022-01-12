import { kea } from 'kea'
import { OrganizationInviteType } from '~/types'
import api from 'lib/api'
import { toast } from 'react-toastify'
import { organizationLogic } from 'scenes/organizationLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { inviteLogicType } from './inviteLogicType'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import { successToast } from 'lib/utils'

/** State of a single invite row (with input data) in bulk invite creation. */
interface InviteRowState {
    target_email: string
    first_name: string
    isValid: boolean
}

const EMPTY_INVITE: InviteRowState = { target_email: '', first_name: '', isValid: true }

export const inviteLogic = kea<inviteLogicType<InviteRowState>>({
    path: ['scenes', 'organization', 'Settings', 'inviteLogic'],
    actions: {
        updateInviteAtIndex: (payload, index: number) => ({ payload, index }),
        deleteInviteAtIndex: (index: number) => ({ index }),
        appendInviteRow: true,
        resetInviteRows: true,
    },
    reducers: {
        invitesToSend: [
            [EMPTY_INVITE] as InviteRowState[],
            {
                updateInviteAtIndex: (state, { payload, index }) => {
                    const newState = [...state]
                    newState[index] = { ...state[index], ...payload }
                    return newState
                },
                deleteInviteAtIndex: (state, { index }) => {
                    const newState = [...state]
                    newState.splice(index, 1)
                    return newState
                },
                appendInviteRow: (state) => [...state, EMPTY_INVITE],
                resetInviteRows: () => [EMPTY_INVITE],
            },
        ],
    },
    selectors: {
        canSubmit: [
            (selectors) => [selectors.invitesToSend],
            (invites: InviteRowState[]) =>
                invites.filter(({ target_email }) => !!target_email).length > 0 &&
                invites.filter(({ isValid }) => !isValid).length == 0,
        ],
    },
    loaders: ({ values }) => ({
        _invitedTeamMembers: [
            [] as OrganizationInviteType[],
            {
                inviteTeamMembers: async () => {
                    if (!values.canSubmit) {
                        return { invites: [] }
                    }

                    const payload: Pick<OrganizationInviteType, 'target_email' | 'first_name'>[] =
                        values.invitesToSend.filter((invite) => invite.target_email)
                    eventUsageLogic.actions.reportBulkInviteAttempted(
                        payload.length,
                        payload.filter((invite) => !!invite.first_name).length
                    )

                    return await api.create('api/organizations/@current/invites/bulk/', payload)
                },
            },
        ],
        invites: {
            __default: [] as OrganizationInviteType[],
            loadInvites: async () => {
                return (await api.get('api/organizations/@current/invites/')).results
            },
            deleteInvite: async (invite: OrganizationInviteType) => {
                await api.delete(`api/organizations/@current/invites/${invite.id}/`)
                preflightLogic.actions.loadPreflight() // Make sure licensed_users_available is updated
                successToast('Invite revoked successfully', `Invite for ${invite.target_email} has been revoked.`)
                return values.invites.filter((thisInvite) => thisInvite.id !== invite.id)
            },
        },
    }),
    listeners: ({ values, actions }) => ({
        inviteTeamMembersSuccess: (): void => {
            const inviteCount = values._invitedTeamMembers.length
            toast.success(`Invited ${inviteCount} new team member${inviteCount === 1 ? '' : 's'}`)
            organizationLogic.actions.loadCurrentOrganization()
            actions.loadInvites()
            actions.resetInviteRows()
        },
    }),
    events: ({ actions }) => ({
        afterMount: [actions.loadInvites],
    }),
})
