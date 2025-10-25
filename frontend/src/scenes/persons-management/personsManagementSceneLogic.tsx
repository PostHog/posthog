import { connect, kea, path, selectors } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { GroupsAccessStatus } from 'lib/introductions/groupsAccessLogic'
import { LemonTab } from 'lib/lemon-ui/LemonTabs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { capitalizeFirstLetter } from 'lib/utils'
import { groupsSceneLogic } from 'scenes/groups/groupsSceneLogic'
import { urls } from 'scenes/urls'

import { groupsModel } from '~/models/groupsModel'

import type { personsManagementSceneLogicType } from './personsManagementSceneLogicType'

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
    selectors({
        tabs: [
            (s) => [s.groupTabs],
            (groupTabs): PersonsManagementTab[] => {
                return [
                    {
                        key: 'persons',
                        url: urls.persons(),
                        label: 'Persons',
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
            (s) => [s.groupTypes, s.groupsAccessStatus, s.aggregationLabel],
            (groupTypes, groupsAccessStatus, aggregationLabel): PersonsManagementTab[] => {
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
                          },
                      ]
                    : Array.from(groupTypes.values()).map(({ group_type_index }) => ({
                          key: `groups-${group_type_index}`,
                          label: capitalizeFirstLetter(aggregationLabel(group_type_index).plural),
                          url: urls.groups(group_type_index),
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
                    tooltipDocLink: tab.tooltipDocLink,
                    link: tab.url,
                })),
        ],
    }),
])
