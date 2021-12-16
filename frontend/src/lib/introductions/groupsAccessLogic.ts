import { kea } from 'kea'
import { AvailableFeature } from '~/types'
import { teamLogic } from 'scenes/teamLogic'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import { userLogic } from 'scenes/userLogic'

import { groupsAccessLogicType } from './groupsAccessLogicType'
export enum GroupsAccessStatus {
    AlreadyUsing,
    HasAccess,
    HasGroupTypes,
    NoAccess,
    Hidden,
}

export const groupsAccessLogic = kea<groupsAccessLogicType<GroupsAccessStatus>>({
    path: ['lib', 'introductions', 'groupsAccessLogic'],
    connect: {
        values: [
            teamLogic,
            ['currentTeam'],
            preflightLogic,
            ['clickhouseEnabled', 'preflight'],
            userLogic,
            ['hasAvailableFeature', 'upgradeLink'],
        ],
    },
    selectors: {
        groupsCanBeEnabled: [(s) => [s.clickhouseEnabled], (clickhouseEnabled) => clickhouseEnabled],
        groupsEnabled: [
            (s) => [s.groupsCanBeEnabled, s.hasAvailableFeature],
            (groupsCanBeEnabled, hasAvailableFeature) =>
                groupsCanBeEnabled && hasAvailableFeature(AvailableFeature.GROUP_ANALYTICS),
        ],
        // Used to toggle various introduction views related to groups
        groupsAccessStatus: [
            (s) => [s.groupsCanBeEnabled, s.groupsEnabled, s.currentTeam, s.preflight],
            (canBeEnabled, isEnabled, currentTeam, preflight): GroupsAccessStatus => {
                const hasGroups = currentTeam?.has_group_types
                if (!canBeEnabled || preflight?.instance_preferences?.disable_paid_fs) {
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
        showGroupsAnnouncementBanner: [(s) => [s.groupsAccessStatus], (status) => status !== GroupsAccessStatus.Hidden],
    },
})
