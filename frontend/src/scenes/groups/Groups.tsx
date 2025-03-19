import { useActions, useValues } from 'kea'
import { groupsAccessLogic, GroupsAccessStatus } from 'lib/introductions/groupsAccessLogic'
import { GroupsIntroduction } from 'scenes/groups/GroupsIntroduction'

import { Query } from '~/queries/Query/Query'

import { groupsListLogic } from './groupsListLogic'

export function Groups({ groupTypeIndex }: { groupTypeIndex: number }): JSX.Element {
    const { query } = useValues(groupsListLogic({ groupTypeIndex }))
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
                emptyStateHeading: 'No groups found',
            }}
            dataAttr="groups-table"
        />
    )
}
