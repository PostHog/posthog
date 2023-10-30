import { actions, connect, kea, path, reducers, selectors, useActions, useValues } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'
import { urls } from 'scenes/urls'
import { LemonTab, LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { SceneExport } from 'scenes/sceneTypes'
import { Breadcrumb } from '~/types'
import { capitalizeFirstLetter } from 'lib/utils'
import { GroupsAccessStatus, groupsAccessLogic } from 'lib/introductions/groupsAccessLogic'

import type { personsManagementSceneLogicType } from './PersonsManagementSceneType'
import { Persons } from './tabs/Persons'
import { groupsModel } from '~/models/groupsModel'
import { Cohorts } from 'scenes/cohorts/Cohorts'
import { LemonButton } from '@posthog/lemon-ui'
import { PageHeader } from 'lib/components/PageHeader'

export type PersonsManagementTabs = Record<
    string,
    { url: string; label: LemonTab<any>['label']; content: any; buttons?: any }
>

const personsManagementSceneLogic = kea<personsManagementSceneLogicType>([
    path(['scenes', 'persons-management', 'personsManagementSceneLogic']),
    connect({
        values: [groupsAccessLogic, ['groupsAccessStatus'], groupsModel, ['groupTypes']],
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
            (s) => [s.groupsAccessStatus],
            (groupsAccessStatus): PersonsManagementTabs => {
                const showGroupsIntroductionPage = [
                    GroupsAccessStatus.HasAccess,
                    GroupsAccessStatus.HasGroupTypes,
                    GroupsAccessStatus.NoAccess,
                ].includes(groupsAccessStatus)

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

export function PersonsManagementScene(): JSX.Element {
    const { tabs, tab, groupTypes } = useValues(personsManagementSceneLogic)
    const { setTab } = useActions(personsManagementSceneLogic)
    const { showGroupsOptions } = useValues(groupsModel)

    console.log(groupTypes)

    const lemonTabs: LemonTab<string>[] = Object.entries(tabs).map(([key, tab]) => ({
        key: key,
        label: <span data-attr={`persons-management-${key}-tab`}>{tab.label}</span>,
        content: tab.content,
    }))

    return (
        <>
            <PageHeader
                title={`Persons${showGroupsOptions ? ', cohorts & groups' : '& cohorts'}`}
                caption={`A catalog of your product's end users, lists of users who have something in common to use in analytics or feature flags${
                    showGroupsOptions ? ' and groups' : ''
                }.`}
                buttons={tabs[tab].buttons}
            />

            <LemonTabs activeKey={tab} onChange={(t) => setTab(t)} tabs={lemonTabs} />
        </>
    )
}

export const scene: SceneExport = {
    component: PersonsManagementScene,
    logic: personsManagementSceneLogic,
}
