import { LemonButton } from '@posthog/lemon-ui'
import { actions, connect, kea, path, reducers, selectors } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'
import { GroupsAccessStatus } from 'lib/introductions/groupsAccessLogic'
import { LemonTab } from 'lib/lemon-ui/LemonTabs'
import { capitalizeFirstLetter } from 'lib/utils'
import { Cohorts } from 'scenes/cohorts/Cohorts'
import { Groups } from 'scenes/groups/Groups'
import { groupsSceneLogic } from 'scenes/groups/groupsSceneLogic'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { groupsModel } from '~/models/groupsModel'
import { Breadcrumb } from '~/types'

import type { personsManagementSceneLogicType } from './personsManagementSceneLogicType'
import { Persons } from './tabs/Persons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'

export type PersonsManagementTab = {
    key: string
    url: string
    label: string | JSX.Element
    content: any
    buttons?: any
    tooltipDocLink?: string
}

export type PersonsManagementTabs = Record<
    string,
    { url: string; label: LemonTab<any>['label']; content: any; buttons?: any }
>

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
                        content: <Persons />,
                        tooltipDocLink: 'https://posthog.com/docs/data/persons',
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
                        tooltipDocLink: 'https://posthog.com/docs/data/cohorts',
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
                              content: <Groups groupTypeIndex={0} />,
                          },
                      ]
                    : Array.from(groupTypes.values()).map(({ group_type_index }) => ({
                          key: `groups-${group_type_index}`,
                          label: capitalizeFirstLetter(aggregationLabel(group_type_index).plural),
                          url: urls.groups(group_type_index),
                          content: <Groups groupTypeIndex={group_type_index} />,
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
            let tabUrl = values.tabs.find((x) => x.key === tabKey)?.url
            if (!tabUrl && values.groupTypesLoading) {
                const groupMatch = tabKey.match(/^groups-(\d+)$/)
                if (groupMatch) {
                    tabUrl = urls.groups(parseInt(groupMatch[1]))
                }
            }
            if (!tabUrl) {
                return values.tabs[0].url
            }
            const newSearchParams = new URLSearchParams(router.values.searchParams)
            newSearchParams.delete('search')
            return [tabUrl, newSearchParams, router.values.hashParams, { replace: false }]
        },
    })),
    urlToAction(({ actions, values }) => {
        const urlToAction = {
            [urls.persons()]: () => {
                if (values.activeTab?.key === 'persons') {
                    return
                }
                actions.setTabKey('persons')
            },
            [urls.cohorts()]: () => {
                if (values.activeTab?.key === 'cohorts') {
                    return
                }
                actions.setTabKey('cohorts')
            },
        } as Record<string, (...args: any[]) => void>
        urlToAction[urls.groups(':key')] = ({ key }: { key: string }) => {
            actions.setTabKey(`groups-${key}`)
            actions.setGroupTypeIndex(parseInt(key))
        }
        return urlToAction
    }),
])
