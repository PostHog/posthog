import { useActions, useValues } from 'kea'
import { groupsAccessLogic, GroupsAccessStatus } from 'lib/introductions/groupsAccessLogic'
import { capitalizeFirstLetter } from 'lib/utils'
import { groupsModel } from '~/models/groupsModel'
import { groupsListLogic } from './groupsListLogic'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'

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
        <LemonTabs
            activeKey={currentTab}
            onChange={(activeKey) => setTab(activeKey)}
            tabs={[
                {
                    key: '-1',
                    label: 'Persons',
                },
                ...(showGroupsIntroductionPage
                    ? [
                          {
                              key: '0',
                              label: 'Groups',
                          },
                      ]
                    : groupTypes.map((groupType) => ({
                          label: capitalizeFirstLetter(aggregationLabel(groupType.group_type_index).plural),
                          key: String(groupType.group_type_index),
                      }))),
            ]}
        />
    )
}
