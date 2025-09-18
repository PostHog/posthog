import { afterMount, connect, kea, listeners, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'

import api from 'lib/api'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { GroupsAccessStatus, groupsAccessLogic } from 'lib/introductions/groupsAccessLogic'
import { wordPluralize } from 'lib/utils'
import { projectLogic } from 'scenes/projectLogic'

import { GroupType, GroupTypeIndex } from '~/types'

import type { groupsModelType } from './groupsModelType'

export interface Noun {
    singular: string
    plural: string
}

export const groupsModel = kea<groupsModelType>([
    path(['models', 'groupsModel']),
    connect(() => ({
        values: [projectLogic, ['currentProjectId'], groupsAccessLogic, ['groupsEnabled', 'groupsAccessStatus']],
    })),
    loaders(({ values }) => ({
        groupTypesRaw: [
            [] as Array<GroupType>,
            {
                loadAllGroupTypes: async () => {
                    if (!values.currentProjectId) {
                        return []
                    }
                    return await api.get(`api/projects/${values.currentProjectId}/groups_types`)
                },
                updateGroupTypesMetadata: async (payload: Array<GroupType>) => {
                    if (values.groupsEnabled) {
                        return await api.update(
                            `/api/projects/${values.currentProjectId}/groups_types/update_metadata`,
                            payload
                        )
                    }
                    return []
                },
                deleteGroupType: async (groupTypeIndex: number) => {
                    if (values.groupsEnabled) {
                        await api.delete(`/api/projects/${values.currentProjectId}/groups_types/${groupTypeIndex}`)
                    }
                    return []
                },
                createDetailDashboard: async (groupTypeIndex: number) => {
                    const groupType = await api.put(
                        `/api/projects/${values.currentProjectId}/groups_types/create_detail_dashboard`,
                        { group_type_index: groupTypeIndex }
                    )
                    return values.groupTypesRaw.map((gt) => (gt.group_type_index === groupTypeIndex ? groupType : gt))
                },
                removeDetailDashboard: async (dashboardId: number) => {
                    return values.groupTypesRaw.map((gt) => {
                        if (gt.detail_dashboard === dashboardId) {
                            return {
                                ...gt,
                                detail_dashboard: null,
                            }
                        }
                        return gt
                    })
                },
                setDefaultColumns: async ({
                    groupTypeIndex,
                    defaultColumns,
                }: {
                    groupTypeIndex: number
                    defaultColumns: string[]
                }) => {
                    const groupType = await api.put(
                        `/api/projects/${values.currentProjectId}/groups_types/set_default_columns`,
                        { group_type_index: groupTypeIndex, default_columns: defaultColumns }
                    )
                    return values.groupTypesRaw.map((gt) => (gt.group_type_index === groupTypeIndex ? groupType : gt))
                },
            },
        ],
    })),
    selectors({
        groupTypes: [
            (s) => [s.groupTypesRaw],
            (groupTypesRaw) =>
                new Map<GroupTypeIndex, GroupType>(
                    groupTypesRaw.map((groupType) => [groupType.group_type_index, groupType])
                ),
        ],
        groupTypesLoading: [(s) => [s.groupTypesRawLoading], (groupTypesRawLoading) => groupTypesRawLoading],

        showGroupsOptions: [
            (s) => [s.groupsAccessStatus, s.groupsEnabled, s.groupTypes],
            (status, enabled, groupTypes) =>
                status !== GroupsAccessStatus.Hidden || (enabled && Array.from(groupTypes.values()).length > 0),
        ],
        groupsTaxonomicTypes: [
            (s) => [s.groupTypes],
            (groupTypes): TaxonomicFilterGroupType[] => {
                return Array.from(groupTypes.values()).map(
                    (groupType: GroupType) =>
                        `${TaxonomicFilterGroupType.GroupsPrefix}_${groupType.group_type_index}` as unknown as TaxonomicFilterGroupType
                )
            },
        ],
        groupNamesTaxonomicTypes: [
            (s) => [s.groupTypes],
            (groupTypes): TaxonomicFilterGroupType[] => {
                return Array.from(groupTypes.values()).map(
                    (groupType: GroupType) =>
                        `${TaxonomicFilterGroupType.GroupNamesPrefix}_${groupType.group_type_index}` as unknown as TaxonomicFilterGroupType
                )
            },
        ],
        aggregationLabel: [
            (s) => [s.groupTypes],
            (groupTypes) =>
                (groupTypeIndex: number | null | undefined, deferToUserWording: boolean = false): Noun => {
                    if (groupTypeIndex != undefined) {
                        const groupType = groupTypes.get(groupTypeIndex as GroupTypeIndex)
                        if (groupType) {
                            return {
                                singular: groupType.name_singular || groupType.group_type,
                                plural: groupType.name_plural || wordPluralize(groupType.group_type),
                            }
                        }
                        return {
                            singular: 'unknown group',
                            plural: 'unknown groups',
                        }
                    }
                    return deferToUserWording
                        ? {
                              singular: 'user',
                              plural: 'users',
                          }
                        : { singular: 'person', plural: 'persons' }
                },
        ],
    }),
    subscriptions(({ values }) => ({
        groupsEnabled: (enabled) => {
            // Load the groups types in the case of groups becoming an available feature after this logic is mounted
            if (!values.groupTypesLoading && enabled) {
                groupsModel.actions.loadAllGroupTypes()
            }
        },
    })),
    listeners(({ actions }) => ({
        deleteGroupTypeSuccess: () => {
            actions.loadAllGroupTypes()
        },
    })),
    afterMount(({ actions }) => {
        if (window.POSTHOG_APP_CONTEXT?.current_team?.group_types) {
            actions.loadAllGroupTypesSuccess(window.POSTHOG_APP_CONTEXT.current_team.group_types)
        } else {
            actions.loadAllGroupTypes()
        }
    }),
])
