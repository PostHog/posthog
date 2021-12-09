import { Tabs } from 'antd'
import { useActions, useValues } from 'kea'
import { groupsAccessLogic, GroupsAccessStatus } from 'lib/introductions/groupsAccessLogic'
import { capitalizeFirstLetter } from 'lib/utils'
import React from 'react'
import { groupsModel } from '~/models/groupsModel'
import { groupsListLogic } from './groupsListLogic'
import { LemonTag } from 'lib/components/LemonTag/LemonTag'

export function GroupsTabs(): JSX.Element {
    const { setTab } = useActions(groupsListLogic)
    const { currentTab } = useValues(groupsListLogic)
    const { groupTypes } = useValues(groupsModel)
    const { groupsAccessStatus } = useValues(groupsAccessLogic)

    const showGroupsIntroductionPage = [
        GroupsAccessStatus.HasAccess,
        GroupsAccessStatus.HasGroupTypes,
        GroupsAccessStatus.NoAccess,
    ].includes(groupsAccessStatus)

    return (
        <Tabs activeKey={currentTab} onChange={(activeKey) => setTab(activeKey)}>
            <Tabs.TabPane tab="Persons" key="-1" />

            {showGroupsIntroductionPage ? (
                <Tabs.TabPane
                    tab={
                        <>
                            Introducing Group analytics
                            <LemonTag type="success" style={{ marginLeft: 4 }}>
                                New
                            </LemonTag>
                        </>
                    }
                    key="0"
                />
            ) : (
                groupTypes.map((groupType) => (
                    <Tabs.TabPane tab={capitalizeFirstLetter(groupType.group_type)} key={groupType.group_type_index} />
                ))
            )}
        </Tabs>
    )
}
