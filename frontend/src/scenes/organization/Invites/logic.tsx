import React from 'react'
import { kea } from 'kea'
import api from 'lib/api'
import { toast } from 'react-toastify'
import { CheckCircleOutlined } from '@ant-design/icons'
import { OrganizationInviteType } from '~/types'
import { invitesLogicType } from 'types/scenes/organization/invitesLogicType'

export const invitesLogic = kea<invitesLogicType>({
    loaders: ({ values }) => ({
        invites: {
            __default: [] as OrganizationInviteType[],
            loadInvites: async () => {
                return (await api.get('api/organizations/@current/invites/')).results
            },
            createInvite: async ({ targetEmail }: { targetEmail?: string }) => {
                const newInvite: OrganizationInviteType = await api.create('api/organizations/@current/invites/', {
                    target_email: targetEmail,
                })
                toast(
                    <div className="text-success">
                        <CheckCircleOutlined /> Invite for {targetEmail}{' '}
                        {newInvite.emailing_attempt_made ? 'sent by email' : 'created'}!
                    </div>
                )
                return [newInvite, ...values.invites]
            },
            deleteInvite: async (invite: OrganizationInviteType) => {
                await api.delete(`api/organizations/@current/invites/${invite.id}/`)
                toast(
                    <div className="text-success">
                        <CheckCircleOutlined /> Invite for {invite.target_email} removed!
                    </div>
                )
                return values.invites.filter((thisInvite) => thisInvite.id !== invite.id)
            },
        },
    }),
    events: ({ actions }) => ({
        afterMount: actions.loadInvites,
    }),
})
