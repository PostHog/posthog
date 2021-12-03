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
            ['hasAvailableFeature'],
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
                groupsCanBeEnabled && hasAvailableFeature(AvailableFeature.CORRELATION_ANALYSIS),
        ],
        // Used to toggle various upsell mechanisms for groups
        groupsAccessStatus: [
            (s) => [s.groupsCanBeEnabled, s.groupsEnabled, s.currentTeam, s.preflight],
            (canBeEnabled, isEnabled, currentTeam, preflight): GroupsAccessStatus => {
                const hasGroups = currentTeam?.has_group_types
                const hideUpsell = preflight?.instance_preferences?.disable_paid_fs
                if (!canBeEnabled) {
                    return GroupsAccessStatus.Hidden
                } else if (isEnabled && hasGroups) {
                    return GroupsAccessStatus.AlreadyUsing
                } else if (hideUpsell) {
                    return GroupsAccessStatus.Hidden
                } else if (isEnabled) {
                    return GroupsAccessStatus.HasAccess
                } else if (hasGroups) {
                    return GroupsAccessStatus.HasGroupTypes
                } else {
                    return GroupsAccessStatus.NoAccess
                }
            },
        ],
        upgradeLink: [
            (s) => [s.preflight],
            (preflight) => (preflight?.cloud ? '/organization/billing' : '/instance/licenses'),
        ],
    },
})
