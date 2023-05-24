import { useValues } from 'kea'
import { groupsAccessLogic, GroupsAccessStatus } from 'lib/introductions/groupsAccessLogic'
import { capitalizeFirstLetter } from 'lib/utils'
import { groupsModel } from '~/models/groupsModel'
import { LemonTab, LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { urls } from 'scenes/urls'

export function GroupsTabs({ activeGroupTypeIndex }: { activeGroupTypeIndex: number }): JSX.Element {
    const { groupTypes, aggregationLabel } = useValues(groupsModel)
    const { groupsAccessStatus } = useValues(groupsAccessLogic)

    const showGroupsIntroductionPage = [
        GroupsAccessStatus.HasAccess,
        GroupsAccessStatus.HasGroupTypes,
        GroupsAccessStatus.NoAccess,
    ].includes(groupsAccessStatus)

    return (
        <LemonTabs
            activeKey={activeGroupTypeIndex}
            tabs={[
                {
                    key: -1,
                    label: 'Persons',
                    to: urls.persons(),
                },
                ...(showGroupsIntroductionPage
                    ? [
                          {
                              key: 0,
                              label: 'Groups',
                          },
                      ]
                    : groupTypes.map(
                          (groupType) =>
                              ({
                                  label: capitalizeFirstLetter(aggregationLabel(groupType.group_type_index).plural),
                                  key: groupType.group_type_index,
                                  to: urls.groups(groupType.group_type_index),
                              } as LemonTab<number>)
                      )),
            ]}
        />
    )
}
