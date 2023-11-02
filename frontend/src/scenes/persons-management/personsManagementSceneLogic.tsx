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

export type PersonsManagementTabs = Record<
    string,
    { url: string; label: LemonTab<any>['label']; content: any; buttons?: any }
>

export const personsManagementSceneLogic = kea<personsManagementSceneLogicType>([
    path(['scenes', 'persons-management', 'personsManagementSceneLogic']),
    connect({
        values: [groupsModel, ['groupTypes', 'groupsAccessStatus']],
    }),
    actions({
        setTab: (tab: string) => ({ tab }),
    }),
    reducers({
        tab: [
            'persons' as string,
            {
                setTab: (_, { tab }) => tab,
            },
        ],
    }),
    selectors({
        tabs: [
            (s) => [s.groupTabs],
            (groupTabs): PersonsManagementTabs => {
                return {
                    persons: {
                        url: urls.persons(),
                        label: 'Persons',
                        content: <Persons />,
                    },
                    cohorts: {
                        url: urls.cohorts(),
                        label: 'Cohorts',
                        content: <Cohorts />,
                        buttons: (
                            <LemonButton
                                type="primary"
                                data-attr="create-cohort"
                                onClick={() => router.actions.push(urls.cohort('new'))}
                            >
                                New Cohort
                            </LemonButton>
                        ),
                    },
                    ...groupTabs,
                    // ...(showGroupsIntroductionPage
                    //     ?
                    //         {
                    //             label: 'Groups',
                    //             content: <p>Yo</p>
                    //             url: urls.groups(0),
                    //         },

                    //     : groupTypes.values()).map(
                    //           (groupType) =>
                    //               ({
                    //                   label: capitalizeFirstLetter(aggregationLabel(groupType.group_type_index).plural),
                    //                   key: groupType.group_type_index,
                    //                   link: urls.groups(groupType.group_type_index),
                    //               } as LemonTab<number>)
                    //       )),
                }
            },
        ],

        groupTabs: [
            (s) => [s.groupTypes, s.groupsAccessStatus],
            (groupTypes, groupsAccessStatus): PersonsManagementTabs => {
                const showGroupsIntroductionPage = [
                    GroupsAccessStatus.HasAccess,
                    GroupsAccessStatus.HasGroupTypes,
                    GroupsAccessStatus.NoAccess,
                ].includes(groupsAccessStatus)

                console.log({ groupTypes, groupsAccessStatus, showGroupsIntroductionPage })
                return {}
            },
        ],
        breadcrumbs: [
            (s) => [s.tabs, s.tab],
            (tabs, tab): Breadcrumb[] => {
                return [
                    {
                        name: `Persons`,
                        path: tabs.persons.url,
                    },
                    {
                        name: capitalizeFirstLetter(tab),
                        path: tabs[tab].url,
                    },
                ]
            },
        ],
    }),
    actionToUrl(({ values }) => ({
        setTab: ({ tab }) => values.tabs[tab]?.url || values.tabs.persons.url,
    })),
    urlToAction(({ actions, values }) => {
        return Object.fromEntries(
            Object.entries(values.tabs).map(([key, tab]) => [
                tab.url,
                () => {
                    if (values.tab !== key) {
                        actions.setTab(key)
                    }
                },
            ])
        )
    }),
])
