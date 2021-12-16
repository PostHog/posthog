import { kea } from 'kea'
import { AvailableFeature } from '~/types'
import { teamLogic } from 'scenes/teamLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
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
            featureFlagLogic,
            ['featureFlags'],
            preflightLogic,
            ['clickhouseEnabled', 'preflight'],
            userLogic,
            ['hasAvailableFeature', 'upgradeLink'],
        ],
    },
    selectors: {
        groupsCanBeEnabled: [
            (s) => [s.featureFlags, s.clickhouseEnabled],
            (featureFlags, clickhouseEnabled) => featureFlags[FEATURE_FLAGS.GROUP_ANALYTICS] && clickhouseEnabled,
        ],
        groupsEnabled: [
            (s) => [s.groupsCanBeEnabled, s.hasAvailableFeature],
            (groupsCanBeEnabled, hasAvailableFeature) =>
                groupsCanBeEnabled && hasAvailableFeature(AvailableFeature.GROUP_ANALYTICS),
        ],
        // Used to toggle various introduction views related to groups
        groupsAccessStatus: [
            (s) => [s.featureFlags, s.groupsCanBeEnabled, s.groupsEnabled, s.currentTeam, s.preflight],
            (featureFlags, canBeEnabled, isEnabled, currentTeam, preflight): GroupsAccessStatus => {
                const hasGroups = currentTeam?.has_group_types
                if (
                    !canBeEnabled ||
                    preflight?.instance_preferences?.disable_paid_fs ||
                    !featureFlags[FEATURE_FLAGS.GROUP_ANALYTICS_INTRODUCTION]
                ) {
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
