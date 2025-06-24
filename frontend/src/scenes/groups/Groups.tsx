import { useActions, useValues } from 'kea'
import { groupsAccessLogic, GroupsAccessStatus } from 'lib/introductions/groupsAccessLogic'
import { Link } from 'lib/lemon-ui/Link'
import { GroupsIntroduction } from 'scenes/groups/GroupsIntroduction'
import { SceneExport } from 'scenes/sceneTypes'

import { Query } from '~/queries/Query/Query'
import { GroupTypeIndex } from '~/types'

import { groupsListLogic } from './groupsListLogic'
import { groupsSceneLogic } from './groupsSceneLogic'
export function Groups({ groupTypeIndex }: { groupTypeIndex: GroupTypeIndex }): JSX.Element {
    const { groupTypeName, groupTypeNamePlural } = useValues(groupsSceneLogic)
    const { query, queryWasModified } = useValues(groupsListLogic({ groupTypeIndex }))
    const { setQuery } = useActions(groupsListLogic({ groupTypeIndex }))
    const { groupsAccessStatus } = useValues(groupsAccessLogic)

    if (groupTypeIndex === undefined) {
        throw new Error('groupTypeIndex is undefined')
    }

    if (
        groupsAccessStatus == GroupsAccessStatus.HasAccess ||
        groupsAccessStatus == GroupsAccessStatus.HasGroupTypes ||
        groupsAccessStatus == GroupsAccessStatus.NoAccess
    ) {
        return (
            <>
                <GroupsIntroduction />
            </>
        )
    }

    return (
        <Query
            query={query}
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
                columns: {
                    group_name: {
                        title: groupTypeName,
                    },
                },
                groupTypeLabel: groupTypeNamePlural,
            }}
            dataAttr="groups-table"
        />
    )
}

export function GroupsScene(): JSX.Element {
    const { groupTypeIndex } = useValues(groupsSceneLogic)
    return <Groups groupTypeIndex={groupTypeIndex as GroupTypeIndex} />
}

export const scene: SceneExport = {
    component: GroupsScene,
    logic: groupsSceneLogic,
}
