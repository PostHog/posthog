import { kea } from 'kea'
import { bulkInviteLogicType } from './bulkInviteLogicType'
import { OrganizationInviteType } from '~/types'
import api from 'lib/api'
import { toast } from 'react-toastify'
import { organizationLogic } from 'scenes/organizationLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { invitesLogic } from './invitesLogic'

interface InviteRowState {
    target_email: string
    first_name: string
    isValid: boolean
}

const EMPTY_INVITE = { target_email: '', first_name: '', isValid: true }

export const bulkInviteLogic = kea<bulkInviteLogicType<InviteRowState>>({
    actions: {
        updateInviteAtIndex: (payload, index: number) => ({ payload, index }),
        deleteInviteAtIndex: (index: number) => ({ index }),
        appendInviteRow: true,
        resetInviteRows: true,
    },
    reducers: {
        invites: [
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
                appendInviteRow: (state) => {
                    return [...state, EMPTY_INVITE]
                },
                resetInviteRows: () => [EMPTY_INVITE],
            },
        ],
    },
    selectors: {
        canSubmit: [
            (selectors) => [selectors.invites],
            (invites: InviteRowState[]) =>
                invites.filter(({ target_email }) => !!target_email).length > 0 &&
                invites.filter(({ isValid }) => !isValid).length == 0,
        ],
    },
    loaders: ({ values }) => ({
        invitedTeamMembers: [
            [] as OrganizationInviteType[],
            {
                inviteTeamMembers: async () => {
                    if (!values.canSubmit) {
                        return { invites: [] }
                    }

                    const payload: Pick<
                        OrganizationInviteType,
                        'target_email' | 'first_name'
                    >[] = values.invites.filter((invite) => invite.target_email)

                    eventUsageLogic.actions.reportBulkInviteAttempted(
                        payload.length,
                        payload.filter((invite) => !!invite.first_name).length
                    )

                    return await api.create('api/organizations/@current/invites/bulk/', payload)
                },
            },
        ],
    }),
    listeners: ({ values, actions }) => ({
        inviteTeamMembersSuccess: (): void => {
            const inviteCount = values.invitedTeamMembers.length
            toast.success(`Invited ${inviteCount} new team ${inviteCount === 1 ? 'member' : 'members'}.`)
            organizationLogic.actions.loadCurrentOrganization()
            invitesLogic.actions.loadInvites()
            actions.resetInviteRows()
        },
    }),
})
