import { useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { GroupsTabs } from 'scenes/groups/GroupsTabs'
import { groupsModel } from '~/models/groupsModel'

export function PersonPageHeader({ activeGroupTypeIndex }: { activeGroupTypeIndex: number }): JSX.Element {
    const { showGroupsOptions } = useValues(groupsModel)

    return (
        <>
            <PageHeader
                title={`Persons${showGroupsOptions ? ' & Groups' : ''}`}
                caption={`A catalog of your product's end users${showGroupsOptions ? ' and groups' : ''}.`}
            />
            {showGroupsOptions && <GroupsTabs activeGroupTypeIndex={activeGroupTypeIndex} />}
        </>
    )
}
