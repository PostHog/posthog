import React from 'react'
import { useValues } from 'kea'
import { groupsLogic } from './groupsLogic'
import { PageHeader } from 'lib/components/PageHeader'

export function Group(): JSX.Element {
    const { currentGroupId, /* currentGroup, */ currentGroupType } = useValues(groupsLogic)

    if (!currentGroupId) {
        return <div>Group not found</div>
    }
    return (
        <div style={{ marginBottom: 128 }}>
            <PageHeader
                title={
                    <>
                        {currentGroupId} ({currentGroupType})
                    </>
                }
            />
        </div>
    )
}
