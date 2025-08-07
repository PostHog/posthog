import { LemonButton } from '@posthog/lemon-ui'
import { actions, connect, kea, path, reducers, selectors } from 'kea'
import { router } from 'kea-router'
import { GroupsAccessStatus } from 'lib/introductions/groupsAccessLogic'
import { LemonTab } from 'lib/lemon-ui/LemonTabs'
import { capitalizeFirstLetter } from 'lib/utils'
import { groupsSceneLogic } from 'scenes/groups/groupsSceneLogic'
import { urls } from 'scenes/urls'

import { groupsModel } from '~/models/groupsModel'

import type { personsManagementSceneLogicType } from './personsManagementSceneLogicType'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'

export type PersonsManagementTab = {
    key: string
    url: string
    label: string | JSX.Element
    buttons?: any
    tooltipDocLink?: string
}

export const personsManagementSceneLogic = kea<personsManagementSceneLogicType>([
    path(['scenes', 'persons-management', 'personsManagementSceneLogic']),
    connect(() => ({
        actions: [groupsSceneLogic, ['setGroupTypeIndex']],
        values: [
            groupsModel,
            ['aggregationLabel', 'groupTypes', 'groupTypesLoading', 'groupsAccessStatus'],
            featureFlagLogic,
            ['featureFlags'],
        ],
    })),
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
                        // content: <Persons />,
                        tooltipDocLink: 'https://posthog.com/docs/data/persons',
                    },
                    {
                        key: 'cohorts',
                        url: urls.cohorts(),
                        label: 'Cohorts',
                        tooltipDocLink: 'https://posthog.com/docs/data/cohorts',
                    },
                    ...groupTabs,
                ]
            },
        ],
        crmFeatureFlag: [(s) => [s.featureFlags], (featureFlags) => featureFlags[FEATURE_FLAGS.CRM_ITERATION_ONE]],
        groupTabs: [
            (s) => [s.groupTypes, s.groupsAccessStatus, s.aggregationLabel, s.crmFeatureFlag],
            (groupTypes, groupsAccessStatus, aggregationLabel, crmFeatureFlag): PersonsManagementTab[] => {
                const showGroupsIntroductionPage = [
                    GroupsAccessStatus.HasAccess,
                    GroupsAccessStatus.HasGroupTypes,
                    GroupsAccessStatus.NoAccess,
                ].includes(groupsAccessStatus)

                const groupTabs: PersonsManagementTab[] = showGroupsIntroductionPage
                    ? [
                          {
                              key: 'groups-0',
                              label: 'Groups',
                              url: urls.groups(0),
                              // content: <Groups groupTypeIndex={0} />,
                          },
                      ]
                    : Array.from(groupTypes.values()).map(({ group_type_index }) => ({
                          key: `groups-${group_type_index}`,
                          label: capitalizeFirstLetter(aggregationLabel(group_type_index).plural),
                          url: urls.groups(group_type_index),
                          // content: <Groups groupTypeIndex={group_type_index} />,
                          buttons: crmFeatureFlag ? (
                              <LemonButton
                                  type="primary"
                                  data-attr={`new-group-${group_type_index}`}
                                  onClick={() => router.actions.push(urls.group(group_type_index, 'new', false))}
                              >
                                  New {aggregationLabel(group_type_index).singular}
                              </LemonButton>
                          ) : null,
                      }))

                return groupTabs
            },
        ],

        lemonTabs: [
            (s) => [s.tabs],
            (tabs): LemonTab<string>[] =>
                tabs.map((tab) => ({
                    key: tab.key,
                    label: <span data-attr={`persons-management-${tab.key}-tab`}>{tab.label}</span>,
                    // content: tab.content,
                    tooltipDocLink: tab.tooltipDocLink,
                    link: tab.url,
                })),
        ],
        // breadcrumbs: [
        //     (s) => [s.tabs, s.activeTab],
        //     (tabs, activeTab): Breadcrumb[] => {
        //         return [
        //             {
        //                 key: Scene.PersonsManagement,
        //                 name: `People`,
        //                 path: tabs[0].url,
        //             },
        //             activeTab
        //                 ? {
        //                       key: activeTab.key,
        //                       name: activeTab.label,
        //                       path: activeTab.url,
        //                   }
        //                 : {
        //                       key: 'loading',
        //                       name: 'Loading...',
        //                   },
        //         ]
        //     },
        // ],
    }),
    // actionToUrl(({ values }) => ({
    //     setTabKey: ({ tabKey }) => {
    //         let tabUrl = values.tabs.find((x) => x.key === tabKey)?.url
    //         if (!tabUrl && values.groupTypesLoading) {
    //             const groupMatch = tabKey.match(/^groups-(\d+)$/)
    //             if (groupMatch) {
    //                 tabUrl = urls.groups(parseInt(groupMatch[1]))
    //             }
    //         }
    //         if (!tabUrl) {
    //             return values.tabs[0].url
    //         }
    //         // Preserve existing search params when changing tabs
    //         return [tabUrl, router.values.searchParams, router.values.hashParams]
    //     },
    // })),
    // urlToAction(({ actions }) => {
    //     const urlToAction = {
    //         [urls.persons()]: () => {
    //             actions.setTabKey('persons')
    //         },
    //         [urls.cohorts()]: () => {
    //             actions.setTabKey('cohorts')
    //         },
    //     } as Record<string, (...args: any[]) => void>
    //     urlToAction[urls.groups(':key')] = ({ key }: { key: string }) => {
    //         actions.setTabKey(`groups-${key}`)
    //         actions.setGroupTypeIndex(parseInt(key))
    //     }
    //     return urlToAction
    // }),
])
