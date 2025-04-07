import { useActions, useValues } from 'kea'
import { groupsAccessLogic, GroupsAccessStatus } from 'lib/introductions/groupsAccessLogic'
import { GroupsIntroduction } from 'scenes/groups/GroupsIntroduction'
import { SceneExport } from 'scenes/sceneTypes'

import { Query } from '~/queries/Query/Query'
import { GroupTypeIndex } from '~/types'

import { groupsListLogic } from './groupsListLogic'
import { groupsSceneLogic } from './groupsSceneLogic'
export function Groups({ groupTypeIndex }: { groupTypeIndex: GroupTypeIndex }): JSX.Element {
    const { groupTypeName } = useValues(groupsSceneLogic)
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

export function GroupsScene(): JSX.Element {
    const { groupTypeIndex } = useValues(groupsSceneLogic)
    return <Groups groupTypeIndex={groupTypeIndex as GroupTypeIndex} />
}

export const scene: SceneExport = {
    component: GroupsScene,
    logic: groupsSceneLogic,
}
