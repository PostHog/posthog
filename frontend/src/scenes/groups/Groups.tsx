import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconPeople } from '@posthog/icons'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { groupsAccessLogic } from 'lib/introductions/groupsAccessLogic'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Link } from 'lib/lemon-ui/Link'
import { capitalizeFirstLetter } from 'lib/utils'
import { GroupsIntroduction } from 'scenes/groups/GroupsIntroduction'
import { PersonsManagementSceneTabs } from 'scenes/persons-management/PersonsManagementSceneTabs'
import { SceneExport } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { groupsModel } from '~/models/groupsModel'
import { Query } from '~/queries/Query/Query'
import { ProductKey } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'

import { FeedbackBanner } from 'products/customer_analytics/frontend/components/FeedbackBanner'

import { getCRMColumns } from './crm/utils'
import { groupsListLogic } from './groupsListLogic'
import { groupsSceneLogic } from './groupsSceneLogic'

export const scene: SceneExport = {
    component: GroupsScene,
    logic: groupsSceneLogic,
    productKey: ProductKey.GROUP_ANALYTICS,
}

export function GroupsScene({ tabId }: { tabId?: string } = {}): JSX.Element {
    if (!tabId) {
        throw new Error('GroupsScene rendered with no tabId')
    }
    const { groupTypeIndex, groupTypeName, groupTypeNamePlural } = useValues(groupsSceneLogic)

    const mountedGroupsListLogic = groupsListLogic({ groupTypeIndex })
    const { query, queryWasModified } = useValues(mountedGroupsListLogic)
    const { setQuery } = useActions(mountedGroupsListLogic)

    const { shouldShowGroupsIntroduction } = useValues(groupsAccessLogic)
    const { aggregationLabel } = useValues(groupsModel)
    const { baseCurrency } = useValues(teamLogic)
    const hasCustomerAnalyticsEnabled = useFeatureFlag('CUSTOMER_ANALYTICS')

    if (groupTypeIndex === undefined) {
        throw new Error('groupTypeIndex is undefined')
    }

    if (shouldShowGroupsIntroduction) {
        return (
            <SceneContent>
                <PersonsManagementSceneTabs tabKey={`groups-${groupTypeIndex}`} />
                <SceneTitleSection
                    name="Groups"
                    description="Associate events with a group or entity - such as a company, community, or project. Analyze these events as if they were sent by that entity itself. Great for B2B, marketplaces, and more."
                    resourceType={{
                        type: groupTypeName,
                        forceIcon: <IconPeople />,
                    }}
                />
                <GroupsIntroduction />
            </SceneContent>
        )
    }

    let columns = {
        group_name: {
            title: groupTypeName,
        },
    } as QueryContext['columns']
    let hiddenColumns = [] as string[]
    if (hasCustomerAnalyticsEnabled) {
        columns = getCRMColumns(groupTypeName, groupTypeIndex)
        hiddenColumns.push('key')
    }

    return (
        <SceneContent>
            <PersonsManagementSceneTabs tabKey={`groups-${groupTypeIndex}`} />

            <SceneTitleSection
                name={capitalizeFirstLetter(groupTypeNamePlural)}
                description={`A catalog of all ${groupTypeNamePlural} for this project`}
                resourceType={{
                    type: 'cohort',
                }}
                actions={
                    hasCustomerAnalyticsEnabled ? (
                        <LemonButton
                            type="primary"
                            size="small"
                            data-attr={`new-group-${groupTypeIndex}`}
                            onClick={() => router.actions.push(urls.group(groupTypeIndex, 'new', false))}
                        >
                            New {aggregationLabel(groupTypeIndex).singular}
                        </LemonButton>
                    ) : undefined
                }
            />
            <FeedbackBanner
                feedbackButtonId="groups-list"
                message="We're improving the groups experience. Send us your feedback!"
            />

            <Query
                uniqueKey={`groups-query-${tabId}`}
                attachTo={groupsSceneLogic({ tabId })}
                query={{ ...query, hiddenColumns, showCount: true, showTableViews: true }}
                setQuery={setQuery}
                context={{
                    refresh: 'blocking',
                    emptyStateHeading: queryWasModified
                        ? `No ${groupTypeNamePlural} found`
                        : `No ${groupTypeNamePlural} exist because none have been identified`,
                    emptyStateDetail: queryWasModified ? (
                        'Try changing the date range or property filters.'
                    ) : (
                        <>
                            Go to the{' '}
                            <Link to="https://posthog.com/docs/product-analytics/group-analytics#how-to-create-groups">
                                group analytics docs
                            </Link>{' '}
                            to learn what needs to be done
                        </>
                    ),
                    columns,
                    groupTypeLabel: groupTypeNamePlural,
                    baseCurrency,
                }}
                dataAttr="groups-table"
            />
        </SceneContent>
    )
}
