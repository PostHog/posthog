import { Group } from '~/types'

import { RelatedGroups } from '../RelatedGroups'
import { GroupCard } from './GroupCard'

export function GroupPeopleCard({ groupData }: { groupData: Group }): JSX.Element {
    return (
        <GroupCard>
            <RelatedGroups groupTypeIndex={groupData.group_type_index} id={groupData.group_key} />
        </GroupCard>
    )
}
