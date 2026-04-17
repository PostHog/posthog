import { connect, kea, path, selectors } from 'kea'

import { GuestGrant } from '~/types'

import { userLogic } from '../userLogic'
import type { guestSceneLogicType } from './guestSceneLogicType'

export const guestSceneLogic = kea<guestSceneLogicType>([
    path(['scenes', 'guest', 'guestSceneLogic']),

    connect(() => ({ values: [userLogic, ['user']] })),

    selectors({
        isGuest: [(s) => [s.user], (user): boolean => user?.is_guest_in_current_project ?? false],
        grants: [(s) => [s.user], (user): GuestGrant[] => (user?.guest_grants as GuestGrant[]) ?? []],
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
