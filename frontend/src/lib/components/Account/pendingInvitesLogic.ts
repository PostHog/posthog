import { afterMount, kea, path } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { isUserLoggedIn } from 'lib/utils'

import type { pendingInvitesLogicType } from './pendingInvitesLogicType'

export interface PendingInviteForCurrentUser {
    id: string
    target_email: string
    organization_id: string
    organization_name: string
    created_at: string
}

export const pendingInvitesLogic = kea<pendingInvitesLogicType>([
    path(['lib', 'components', 'Account', 'pendingInvitesLogic']),
    loaders({
        pendingInvites: [
            [] as PendingInviteForCurrentUser[],
            {
                loadPendingInvites: async () => {
                    if (!isUserLoggedIn()) {
                        return []
                    }
                    try {
                        return await api.get('api/users/@me/pending_invites/')
                    } catch {
                        return []
                    }
                },
            },
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadPendingInvites()
    }),
])
