import React from 'react'
import { kea } from 'kea'
import api from 'lib/api'
import { toast } from 'react-toastify'
import { CheckCircleOutlined } from '@ant-design/icons'

export type InviteCreationMode = 'wildcard' | 'limited' | 'email'

export const invitesLogic = kea({
    loaders: ({ values }) => ({
        invites: {
            __default: [],
            loadInvites: async () => {
                return (await api.get('api/organizations/@current/invites/')).results
            },
            createInvite: async ({ targetEmail }: { targetEmail?: string }) => {
                const newInvite = await api.create('api/organizations/@current/invites/', { target_email: targetEmail })
                return [newInvite, ...values.invites]
            },
            deleteInvite: async (invite) => {
                await api.delete(`api/organizations/@current/invites/${invite.id}/`)
                toast(
                    <div>
                        <h1 className="text-success">
                            <CheckCircleOutlined /> Invite for {invite.target_email} successfully removed!
                        </h1>
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
