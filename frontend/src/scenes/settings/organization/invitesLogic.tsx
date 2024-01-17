import { events, kea, listeners, path } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { OrganizationInviteType } from '~/types'

import type { invitesLogicType } from './invitesLogicType'

export const invitesLogic = kea<invitesLogicType>([
    path(['scenes', 'organization', 'Settings', 'invitesLogic']),
    loaders(({ values }) => ({
        invites: {
            __default: [] as OrganizationInviteType[],
            loadInvites: async () => {
                return (await api.get('api/organizations/@current/invites/')).results
            },
            createInvite: async ({ targetEmail }: { targetEmail?: string }) => {
                const newInvite: OrganizationInviteType = await api.create('api/organizations/@current/invites/', {
                    target_email: targetEmail,
                })
                preflightLogic.actions.loadPreflight() // Make sure licensed_users_available is updated

                if (newInvite.emailing_attempt_made) {
                    lemonToast.success(
                        <>
                            Invite sent to <b>{targetEmail}</b>'s inbox
                        </>
                    )
                }

                return [newInvite, ...values.invites]
            },
            deleteInvite: async (invite: OrganizationInviteType) => {
                await api.delete(`api/organizations/@current/invites/${invite.id}/`)
                preflightLogic.actions.loadPreflight() // Make sure licensed_users_available is updated
                lemonToast.success(
                    <>
                        Invite for <b>{invite.target_email}</b> removed
                    </>
                )
                return values.invites.filter((thisInvite) => thisInvite.id !== invite.id)
            },
        },
    })),
    listeners({
        createInviteSuccess: () => {
            const nameProvided = false // TODO: Change when adding support for names on invites
            eventUsageLogic.actions.reportInviteAttempted(
                nameProvided,
                !!preflightLogic.values.preflight?.email_service_available
            )
        },
    }),
    events(({ actions }) => ({
        afterMount: actions.loadInvites,
    })),
])
