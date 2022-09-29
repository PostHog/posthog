import { kea } from 'kea'
import { AvailableFeature } from '~/types'
import { teamLogic } from 'scenes/teamLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { userLogic } from 'scenes/userLogic'

import type { groupsAccessLogicType } from './groupsAccessLogicType'
export enum GroupsAccessStatus {
    AlreadyUsing,
    HasAccess,
    HasGroupTypes,
    NoAccess,
    Hidden,
}

export const groupsAccessLogic = kea<groupsAccessLogicType>({
    path: ['lib', 'introductions', 'groupsAccessLogic'],
    connect: {
        values: [
            teamLogic,
            ['currentTeam'],
            preflightLogic,
            ['preflight'],
            userLogic,
            ['hasAvailableFeature', 'upgradeLink'],
        ],
    },
    selectors: {
        groupsEnabled: [
            (s) => [s.hasAvailableFeature],
            (hasAvailableFeature) => hasAvailableFeature(AvailableFeature.GROUP_ANALYTICS),
        ],
        // Used to toggle various introduction views related to groups
        groupsAccessStatus: [
            (s) => [s.groupsEnabled, s.currentTeam, s.preflight],
            (isEnabled, currentTeam, preflight): GroupsAccessStatus => {
                const hasGroups = currentTeam?.has_group_types
                if (preflight?.instance_preferences?.disable_paid_fs) {
                    return GroupsAccessStatus.Hidden
                } else if (isEnabled && hasGroups) {
                    return GroupsAccessStatus.AlreadyUsing
                } else if (isEnabled) {
                    return GroupsAccessStatus.HasAccess
                } else if (hasGroups) {
                    return GroupsAccessStatus.HasGroupTypes
                } else {
                    return GroupsAccessStatus.NoAccess
                }
            },
        ],
    },
})
