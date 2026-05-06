import { connect, kea, path, selectors } from 'kea'

import { userLogic } from 'scenes/userLogic'

import { PendingInviteForCurrentUser } from '~/types'

import type { pendingInvitesLogicType } from './pendingInvitesLogicType'

export type { PendingInviteForCurrentUser }

export const pendingInvitesLogic = kea<pendingInvitesLogicType>([
    path(['lib', 'components', 'Account', 'pendingInvitesLogic']),
    connect(() => ({
        values: [userLogic, ['user']],
    })),
    selectors({
        pendingInvites: [(s) => [s.user], (user): PendingInviteForCurrentUser[] => user?.pending_invites ?? []],
    }),
])
