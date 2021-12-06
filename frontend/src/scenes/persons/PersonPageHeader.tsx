import { useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import React from 'react'
import { GroupsTabs } from 'scenes/groups/GroupsTabs'
import { groupsModel } from '~/models/groupsModel'

export function PersonPageHeader({ hideGroupTabs }: { hideGroupTabs?: boolean }): JSX.Element {
    const { showGroupsOptions } = useValues(groupsModel)

    return (
        <>
            <PageHeader
                title={`Persons${showGroupsOptions ? ' & groups' : ''}`}
                caption={`A catalog of your product's end users${showGroupsOptions ? ' and groups' : ''}.`}
            />
            {!hideGroupTabs && showGroupsOptions && <GroupsTabs />}
        </>
    )
}
