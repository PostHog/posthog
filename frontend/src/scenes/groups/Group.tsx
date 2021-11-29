import React from 'react'
import { useValues } from 'kea'
import { groupLogic } from 'scenes/groups/groupLogic'

export function Group(): JSX.Element {
    const { groupData, groupDataLoading } = useValues(groupLogic)
    return (
        <>
            Hello there<pre>{JSON.stringify({ groupData, groupDataLoading })}</pre>
        </>
    )
}
