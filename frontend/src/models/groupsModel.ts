import { kea } from 'kea'
import api from 'lib/api'
import { Group, GroupType } from '~/types'
import { teamLogic } from 'scenes/teamLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { groupsModelType } from './groupsModelType'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import { urls } from 'scenes/urls'

export const groupsModel = kea<groupsModelType>({
    path: ['models', 'groupsModel'],
    connect: {
        values: [
            teamLogic,
            ['currentTeamId'],
            featureFlagLogic,
            ['featureFlags'],
            preflightLogic,
            ['clickhouseEnabled'],
        ],
    },
    actions: () => ({
        loadGroupList: (groupTypeIndex: string) => ({ groupTypeIndex }),
        setTab: (tab: string) => ({ tab }),
    }),
    loaders: ({ values }) => ({
        groupTypes: [
            [] as Array<GroupType>,
            {
                loadAllGroupTypes: async () => {
                    if (values.groupsEnabled) {
                        return await api.get(`api/projects/${values.currentTeamId}/groups/types`)
                    }
                    return []
                },
            },
        ],
        groupList: [
            [] as Array<Group>,
            {
                loadGroupList: async ({ groupTypeIndex }) => {
                    if (values.groupsEnabled) {
                        return await api.get(
                            `api/projects/${values.currentTeamId}/groups/?group_type_index=${groupTypeIndex}`
                        )
                    }
                    return []
                },
            },
        ],
    }),
    reducers: {
        currentGroup: [
            0,
            {
                setTab: (_, { tab }) => {
                    console.log('tab', tab)
                    return tab
                },
            },
        ],
    },
    selectors: {
        groupsEnabled: [
            (s) => [s.featureFlags, s.clickhouseEnabled],
            (featureFlags, clickhouseEnabled) => featureFlags[FEATURE_FLAGS.GROUP_ANALYTICS] && clickhouseEnabled,
        ],
        showGroupsOptions: [
            (s) => [s.groupsEnabled, s.groupTypes],
            (enabled, groupTypes) => enabled && groupTypes.length > 1,
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
    actionToUrl: () => ({
        setTab: ({ tab }) => {
            if (tab !== '-1') {
                return urls.groups(tab)
            }
            return urls.persons()
        },
    }),
    urlToAction: ({ actions }) => ({
        '/persons/groups/:id': ({ id }) => {
            actions.loadGroupList(id)
            actions.setTab(id)
        },
    }),
    events: ({ actions }) => ({
        afterMount: actions.loadAllGroupTypes,
    }),
})
