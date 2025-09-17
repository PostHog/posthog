import { connect, kea, path, selectors } from 'kea'

import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature } from '~/types'

import type { groupsAccessLogicType } from './groupsAccessLogicType'

export enum GroupsAccessStatus {
    AlreadyUsing,
    HasAccess,
    HasGroupTypes,
    NoAccess,
    Hidden,
}

export const groupsAccessLogic = kea<groupsAccessLogicType>([
    path(['lib', 'introductions', 'groupsAccessLogic']),
    connect(() => ({
        values: [teamLogic, ['currentTeam'], preflightLogic, ['preflight'], userLogic, ['hasAvailableFeature']],
    })),
    selectors({
        groupsEnabled: [
            (s) => [s.hasAvailableFeature],
            (hasAvailableFeature) => hasAvailableFeature(AvailableFeature.GROUP_ANALYTICS),
        ],
        // Used to toggle various introduction views related to groups
        groupsAccessStatus: [
            (s) => [s.groupsEnabled, s.currentTeam, s.preflight],
            (groupsEnabled, currentTeam, preflight): GroupsAccessStatus => {
                const hasGroups = currentTeam?.has_group_types
                if (preflight?.instance_preferences?.disable_paid_fs) {
                    return GroupsAccessStatus.Hidden
                } else if (groupsEnabled && hasGroups) {
                    return GroupsAccessStatus.AlreadyUsing
                } else if (groupsEnabled) {
                    return GroupsAccessStatus.HasAccess
                } else if (hasGroups) {
                    return GroupsAccessStatus.HasGroupTypes
                }
                return GroupsAccessStatus.NoAccess
            },
        ],
        needsUpgradeForGroups: [
            (s) => [s.groupsAccessStatus],
            (groupsAccessStatus) =>
                [GroupsAccessStatus.NoAccess, GroupsAccessStatus.HasGroupTypes].includes(groupsAccessStatus),
        ],
        canStartUsingGroups: [
            (s) => [s.groupsAccessStatus],
            (groupsAccessStatus) => groupsAccessStatus === GroupsAccessStatus.HasAccess,
        ],
    }),
])
