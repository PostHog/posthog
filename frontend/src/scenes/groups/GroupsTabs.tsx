import { Tabs } from 'antd'
import { useActions, useValues } from 'kea'
import { groupsAccessLogic, GroupsAccessStatus } from 'lib/introductions/groupsAccessLogic'
import { capitalizeFirstLetter } from 'lib/utils'
import { groupsModel } from '~/models/groupsModel'
import { groupsListLogic } from './groupsListLogic'

export function GroupsTabs(): JSX.Element {
    const { setTab } = useActions(groupsListLogic)
    const { currentTab } = useValues(groupsListLogic)
    const { groupTypes, aggregationLabel } = useValues(groupsModel)
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
                <Tabs.TabPane tab="Groups" key="0" />
            ) : (
                groupTypes.map((groupType) => (
                    <Tabs.TabPane
                        tab={capitalizeFirstLetter(aggregationLabel(groupType.group_type_index).plural)}
                        key={groupType.group_type_index}
                    />
                ))
            )}
        </Tabs>
    )
}
