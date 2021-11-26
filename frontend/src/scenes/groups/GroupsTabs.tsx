import { Tabs } from 'antd'
import { useActions, useValues } from 'kea'
import { capitalizeFirstLetter } from 'lib/utils'
import React from 'react'
import { groupsModel } from '~/models/groupsModel'
import { groupsListLogic } from './groupsListLogic'

export function GroupsTabs(): JSX.Element {
    const { setTab } = useActions(groupsListLogic)
    const { currentTab } = useValues(groupsListLogic)
    const { groupTypes } = useValues(groupsModel)

    return (
        <Tabs activeKey={currentTab} onChange={(activeKey) => setTab(activeKey)}>
            <Tabs.TabPane tab="Persons" key="-1" />
            {groupTypes.map((groupType) => (
                <Tabs.TabPane tab={capitalizeFirstLetter(groupType.group_type)} key={groupType.group_type_index} />
            ))}
        </Tabs>
    )
}
