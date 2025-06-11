import { actions, connect, kea, path, reducers, selectors } from 'kea'
import { GroupsAccessStatus } from 'lib/introductions/groupsAccessLogic'
import { capitalizeFirstLetter } from 'lib/utils'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { groupsModel } from '~/models/groupsModel'
import { Breadcrumb } from '~/types'

import type { groupsSceneLogicType } from './groupsSceneLogicType'

export type GroupsTab = {
    key: string
    url: string
    label: string
    content: any
    buttons?: any
}

export const groupsSceneLogic = kea<groupsSceneLogicType>([
    path(['scenes', 'groups', 'groupsSceneLogic']),
    connect(() => ({
        values: [groupsModel, ['aggregationLabel', 'groupTypes', 'groupTypesLoading', 'groupsAccessStatus']],
    })),
    actions({
        setGroupTypeIndex: (groupTypeIndex: number) => ({ groupTypeIndex }),
        setTabKey: (tabKey: string) => ({ tabKey }),
    }),
    reducers({
        groupTypeIndex: [
            0,
            {
                setGroupTypeIndex: (_, { groupTypeIndex }) => groupTypeIndex,
            },
        ],
        tabKey: [
            'persons' as string,
            {
                setTabKey: (_, { tabKey }) => tabKey,
            },
        ],
    }),
    selectors({
        tabs: [
            () => [],
            (): GroupsTab[] => {
                return []
            },
        ],
        activeTab: [
            (s) => [s.tabs, s.tabKey],
            (tabs, tabKey): GroupsTab | null => {
                return tabs.find((x) => x.key === tabKey) ?? null
            },
        ],
        groupTypeName: [
            (s) => [s.aggregationLabel, s.groupTypeIndex],
            (aggregationLabel, groupTypeIndex): string => {
                return aggregationLabel(groupTypeIndex).singular
            },
        ],
        groupTypeNamePlural: [
            (s) => [s.aggregationLabel, s.groupTypeIndex],
            (aggregationLabel, groupTypeIndex): string => {
                return aggregationLabel(groupTypeIndex).plural
            },
        ],
        breadcrumbs: [
            (s) => [s.groupTypeIndex, s.groupTypeNamePlural, s.showGroupsIntroductionPage],
            (groupTypeIndex, groupTypeNamePlural, showGroupsIntroductionPage): Breadcrumb[] => {
                return [
                    {
                        key: Scene.Groups,
                        name: showGroupsIntroductionPage ? 'Groups' : capitalizeFirstLetter(groupTypeNamePlural),
                        path: urls.groups(groupTypeIndex),
                    },
                ]
            },
        ],
        showGroupsIntroductionPage: [
            (s) => [s.groupsAccessStatus],
            (groupsAccessStatus): boolean => {
                return [
                    GroupsAccessStatus.HasAccess,
                    GroupsAccessStatus.HasGroupTypes,
                    GroupsAccessStatus.NoAccess,
                ].includes(groupsAccessStatus)
            },
        ],
    }),
])
