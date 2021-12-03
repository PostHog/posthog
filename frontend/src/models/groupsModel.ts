import { kea } from 'kea'
import api from 'lib/api'
import { AvailableFeature, GroupType } from '~/types'
import { teamLogic } from 'scenes/teamLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { groupsModelType } from './groupsModelType'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import { userLogic } from 'scenes/userLogic'

export enum GroupsAccessStatus {
    AlreadyUsing,
    HasAccess,
    HasGroupTypes,
    NoAccess,
    Hidden,
}

export const groupsModel = kea<groupsModelType<GroupsAccessStatus>>({
    path: ['models', 'groupsModel'],
    connect: {
        values: [
            teamLogic,
            ['currentTeam', 'currentTeamId'],
            featureFlagLogic,
            ['featureFlags'],
            preflightLogic,
            ['clickhouseEnabled', 'preflight'],
            userLogic,
            ['hasAvailableFeature'],
        ],
    },
    loaders: ({ values }) => ({
        groupTypes: [
            [] as Array<GroupType>,
            {
                loadAllGroupTypes: async () => {
                    if (values.groupsEnabled) {
                        return await api.get(`api/projects/${values.currentTeamId}/groups_types`)
                    }
                    return []
                },
            },
        ],
    }),
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
        showGroupsOptions: [
            (s) => [s.groupsEnabled, s.groupTypes],
            (enabled, groupTypes) => enabled && groupTypes.length > 0,
        ],
        groupsTaxonomicTypes: [
            (s) => [s.groupTypes],
            (groupTypes): TaxonomicFilterGroupType[] => {
                return groupTypes.map(
                    (groupType: GroupType) =>
                        `${TaxonomicFilterGroupType.GroupsPrefix}_${groupType.group_type_index}` as TaxonomicFilterGroupType
                )
            },
        ],
    },
    events: ({ actions }) => ({
        afterMount: actions.loadAllGroupTypes,
    }),
})
