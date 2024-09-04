import { LemonButton } from '@posthog/lemon-ui'
import { actions, connect, kea, path, reducers, selectors } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'
import { GroupsAccessStatus } from 'lib/introductions/groupsAccessLogic'
import { LemonTab } from 'lib/lemon-ui/LemonTabs'
import { capitalizeFirstLetter } from 'lib/utils'
import { Cohorts } from 'scenes/cohorts/Cohorts'
import { Groups } from 'scenes/groups/Groups'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { groupsModel } from '~/models/groupsModel'
import { Breadcrumb } from '~/types'

import type { personsManagementSceneLogicType } from './personsManagementSceneLogicType'
import { Persons } from './tabs/Persons'

export type PersonsManagementTab = {
    key: string
    url: string
    label: string
    content: any
    buttons?: any
}

export type PersonsManagementTabs = Record<
    string,
    { url: string; label: LemonTab<any>['label']; content: any; buttons?: any }
>

export const personsManagementSceneLogic = kea<personsManagementSceneLogicType>([
    path(['scenes', 'persons-management', 'personsManagementSceneLogic']),
    connect({
        values: [groupsModel, ['aggregationLabel', 'groupTypes', 'groupsAccessStatus', 'aggregationLabel']],
    }),
    actions({
        setTabKey: (tabKey: string, changeUrl?: false | null) => ({ tabKey, changeUrl }),
    }),
    reducers({
        tabKey: [
            'persons' as string,
            {
                setTabKey: (_, { tabKey }) => tabKey,
            },
        ],
    }),
    selectors({
        tabs: [
            (s) => [s.groupTabs],
            (groupTabs): PersonsManagementTab[] => {
                return [
                    {
                        key: 'persons',
                        url: urls.persons(),
                        label: 'People',
                        content: <Persons />,
                    },
                    {
                        key: 'cohorts',
                        url: urls.cohorts(),
                        label: 'Cohorts',
                        content: <Cohorts />,
                        buttons: (
                            <LemonButton
                                type="primary"
                                data-attr="new-cohort"
                                onClick={() => router.actions.push(urls.cohort('new'))}
                            >
                                New cohort
                            </LemonButton>
                        ),
                    },
                    ...groupTabs,
                ]
            },
        ],

        activeTab: [
            (s) => [s.tabs, s.tabKey],
            (tabs, tabKey): PersonsManagementTab | null => {
                return tabs.find((x) => x.key === tabKey) ?? null
            },
        ],

        groupTabs: [
            (s) => [s.groupTypes, s.groupsAccessStatus, s.aggregationLabel],
            (groupTypes, groupsAccessStatus, aggregationLabel): PersonsManagementTab[] => {
                const showGroupsIntroductionPage = [
                    GroupsAccessStatus.HasAccess,
                    GroupsAccessStatus.HasGroupTypes,
                    GroupsAccessStatus.NoAccess,
                ].includes(groupsAccessStatus)

                const groupTabs: PersonsManagementTab[] = [
                    ...(showGroupsIntroductionPage
                        ? [
                              {
                                  key: 'groups-0',
                                  label: 'Groups',
                                  url: urls.groups(0),
                                  content: <Groups groupTypeIndex={0} />,
                              },
                          ]
                        : Array.from(groupTypes.values()).map((groupType) => ({
                              key: `groups-${groupType.group_type_index}`,
                              label: capitalizeFirstLetter(aggregationLabel(groupType.group_type_index).plural),
                              url: urls.groups(groupType.group_type_index),
                              content: <Groups groupTypeIndex={groupType.group_type_index} />,
                          }))),
                ]

                return groupTabs
            },
        ],
        breadcrumbs: [
            (s) => [s.tabs, s.activeTab],
            (tabs, activeTab): Breadcrumb[] => {
                return [
                    {
                        key: Scene.PersonsManagement,
                        name: `People`,
                        path: tabs[0].url,
                    },
                    activeTab
                        ? {
                              key: activeTab.key,
                              name: activeTab.label,
                              path: activeTab.url,
                          }
                        : {
                              key: 'loading',
                              name: 'Loading...',
                          },
                ]
            },
        ],
    }),
    actionToUrl(({ values }) => ({
        setTabKey: ({ tabKey, changeUrl }) => {
            if (changeUrl === false) {
                return
            }
            return values.tabs.find((x) => x.key === tabKey)?.url
        },
    })),
    urlToAction(({ actions }) => {
        return {
            [urls.persons()]: () => {
                actions.setTabKey('persons', false)
            },
            [urls.cohorts()]: () => {
                actions.setTabKey('cohorts', false)
            },
            [urls.groups(':key')]: ({ key }) => {
                actions.setTabKey(`groups-${key}`, false)
            },
            [urls.groups(':key', ':tab')]: ({ key }) => {
                actions.setTabKey(`groups-${key}`, false)
            },
        }
    }),
])
