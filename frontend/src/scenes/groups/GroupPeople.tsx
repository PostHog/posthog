import { Group } from '~/types'

import { RelatedGroups } from './RelatedGroups'

export function GroupPeople({ groupData }: { groupData: Group }): JSX.Element {
    return (
        <div>
            <RelatedGroups groupTypeIndex={groupData.group_type_index} id={groupData.group_key} />
        </div>
    )
}
