import { useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import React from 'react'
import { GroupsTabs } from 'scenes/groups/GroupsTabs'
import { groupsModel } from '~/models/groupsModel'

export function PersonPageHeader({ hideGroupTabs }: { hideGroupTabs?: boolean }): JSX.Element {
    const { groupsEnabled } = useValues(groupsModel)

    return (
        <>
            <PageHeader
                title={`Persons${groupsEnabled ? ' & groups' : ''}`}
                caption={`A catalog of your product's end users${groupsEnabled ? ' and groups' : ''}.`}
            />
            {!hideGroupTabs && groupsEnabled && <GroupsTabs />}
        </>
    )
}
