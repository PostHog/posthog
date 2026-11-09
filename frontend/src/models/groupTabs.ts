import { GroupsAccessStatus } from 'lib/introductions/groupsAccessLogic'
import { capitalizeFirstLetter } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import type { FileSystemIconType } from '~/queries/schema/schema-general'
import type { GroupType, GroupTypeIndex } from '~/types'

import type { Noun } from './groupsModel'

export interface GroupTab {
    key: `groups-${number}`
    label: string
    url: string
    iconType: FileSystemIconType
    // pinned: autocapture dashboards and Playwright select these tabs by data-attr
    dataAttr: string
}

/** One tab for each group type, or one introduction tab when the project cannot use groups yet. */
export function groupTabs(
    groupTypes: Map<GroupTypeIndex, GroupType>,
    groupsAccessStatus: GroupsAccessStatus,
    aggregationLabel: (groupTypeIndex: number | null | undefined, deferToUserWording?: boolean) => Noun
): GroupTab[] {
    const showGroupsIntroductionPage = [
        GroupsAccessStatus.HasAccess,
        GroupsAccessStatus.HasGroupTypes,
        GroupsAccessStatus.NoAccess,
    ].includes(groupsAccessStatus)

    if (showGroupsIntroductionPage) {
        return [
            {
                key: 'groups-0',
                label: 'Groups',
                url: urls.groups(0),
                iconType: 'group',
                dataAttr: 'persons-management-groups-0-tab',
            },
        ]
    }

    return Array.from(groupTypes.values()).map(({ group_type_index }) => ({
        key: `groups-${group_type_index}`,
        label: capitalizeFirstLetter(aggregationLabel(group_type_index).plural),
        url: urls.groups(group_type_index),
        iconType: `group_${group_type_index}` as FileSystemIconType,
        dataAttr: `persons-management-groups-${group_type_index}-tab`,
    }))
}
