import React from 'react'
import { kea } from 'kea'
import api from 'lib/api'
import { toast } from 'react-toastify'
import { CheckCircleOutlined } from '@ant-design/icons'
import { OrganizationInviteType } from '~/types'
import { invitesLogicType } from './invitesLogicType'
import { copyToClipboard } from 'lib/utils'

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

                if (newInvite.emailing_attempt_made) {
                    toast(
                        <div>
                            <h1>Invite sent!</h1>
                            <p>{targetEmail} can now join PostHog by clicking the link on the sent email.</p>
                        </div>
                    )
                } else {
                    const inviteLink = new URL(`/signup/${newInvite.id}`, document.baseURI).href
                    copyToClipboard(inviteLink, `invite link for ${targetEmail}`)
                }

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
