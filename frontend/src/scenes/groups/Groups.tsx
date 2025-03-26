import { useActions, useValues } from 'kea'
import { groupsAccessLogic, GroupsAccessStatus } from 'lib/introductions/groupsAccessLogic'
import { GroupsIntroduction } from 'scenes/groups/GroupsIntroduction'

import { Query } from '~/queries/Query/Query'
import { GroupType } from '~/types'

import { groupsListLogic } from './groupsListLogic'

export function Groups({ groupType }: { groupType: GroupType | undefined }): JSX.Element {
    const { query, groupTypeName } = useValues(groupsListLogic({ groupType }))
    const { setQuery } = useActions(groupsListLogic({ groupType }))
    const { groupsAccessStatus } = useValues(groupsAccessLogic)

    if (groupType === undefined) {
        throw new Error('groupType is undefined')
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
                columns: {
                    group_name: {
                        title: groupTypeName,
                    },
                },
            }}
            dataAttr="groups-table"
        />
    )
}
