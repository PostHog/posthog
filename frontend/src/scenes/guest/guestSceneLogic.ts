import { connect, kea, path, selectors } from 'kea'

import { userLogic } from 'scenes/userLogic'

import { GuestGrant } from '~/types'

import type { guestSceneLogicType } from './guestSceneLogicType'

export const guestSceneLogic = kea<guestSceneLogicType>([
    path(['scenes', 'guest', 'guestSceneLogic']),

    connect(() => ({ values: [userLogic, ['user', 'userLoading']] })),

    selectors({
        isGuest: [(s) => [s.user], (user): boolean => !!user?.is_guest_in_current_project],
        grants: [(s) => [s.user], (user): GuestGrant[] => (user?.guest_grants as GuestGrant[]) ?? []],
        // True only when the user payload has loaded AND there are no grants — distinguishes
        // "really nothing shared" from "we don't know yet because user is still loading."
        showsEmptyState: [
            (s) => [s.user, s.userLoading, s.grants],
            (user, userLoading, grants): boolean => !userLoading && !!user && grants.length === 0,
        ],
        hasMultipleGrants: [(s) => [s.grants], (grants): boolean => grants.length > 1],
        grantsByProject: [
            (s) => [s.grants],
            (grants): Record<number, GuestGrant[]> => {
                const byProject: Record<number, GuestGrant[]> = {}
                for (const grant of grants) {
                    if (!byProject[grant.team_id]) {
                        byProject[grant.team_id] = []
                    }
                    byProject[grant.team_id].push(grant)
                }
                return byProject
            },
        ],
    }),
])
