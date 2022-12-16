import { Tabs } from 'antd'
import { useActions, useValues } from 'kea'
import { groupsAccessLogic, GroupsAccessStatus } from 'lib/introductions/groupsAccessLogic'
import { capitalizeFirstLetter } from 'lib/utils'
import { groupsModel } from '~/models/groupsModel'
import { TabItem } from '~/types'
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

    const getTabItems = (): TabItem[] => {
        const tabItems: TabItem[] = [{ label: 'Persons', key: '-1' }]
        showGroupsIntroductionPage
            ? tabItems.push({ label: 'Groups', key: '0' })
            : groupTypes.map((groupType) =>
                  tabItems.push({
                      label: capitalizeFirstLetter(aggregationLabel(groupType.group_type_index).plural),
                      key: groupType.group_type_index.toString(),
                  })
              )
        return tabItems
    }

    return <Tabs activeKey={currentTab} onChange={(activeKey) => setTab(activeKey)} items={getTabItems()} />
}
