import { actions, connect, kea, path, reducers, selectors } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'
import { urls } from 'scenes/urls'
import { LemonTab } from 'lib/lemon-ui/LemonTabs'
import { Breadcrumb } from '~/types'
import { capitalizeFirstLetter } from 'lib/utils'
import { GroupsAccessStatus } from 'lib/introductions/groupsAccessLogic'

import { groupsModel } from '~/models/groupsModel'
import { Persons } from './tabs/Persons'
import { Cohorts } from 'scenes/cohorts/Cohorts'
import { LemonButton } from '@posthog/lemon-ui'

import type { personsManagementSceneLogicType } from './personsManagementSceneLogicType'
import { Groups } from 'scenes/groups/Groups'
import { Scene } from 'scenes/sceneTypes'

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
        setTabKey: (tabKey: string) => ({ tabKey }),
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
                                New Cohort
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
                                  key: 'groups-intro',
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
        setTabKey: ({ tabKey }) => {
            return values.tabs.find((x) => x.key === tabKey)?.url || values.tabs[0].url
        },
    })),
    urlToAction(({ actions }) => {
        return {
            [urls.persons()]: () => {
                actions.setTabKey('persons')
            },
            [urls.cohorts()]: () => {
                actions.setTabKey('cohorts')
            },
            [urls.groups(':key')]: ({ key }) => {
                actions.setTabKey(`groups-${key}`)
            },
        }
    }),
])
