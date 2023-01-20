import { useActions, useValues } from 'kea'
import { GroupType } from '~/types'
import { LemonTable, LemonTableColumns } from 'lib/components/LemonTable'
import { groupsAccessLogic, GroupsAccessStatus } from 'lib/introductions/groupsAccessLogic'
import { groupAnalyticsConfigLogic } from 'scenes/project/Settings/groupAnalyticsConfigLogic'
import { LemonButton, LemonDivider, LemonInput } from '@posthog/lemon-ui'

export function GroupAnalytics(): JSX.Element | null {
    const { groupTypes, groupTypesLoading, singularChanges, pluralChanges, hasChanges } =
        useValues(groupAnalyticsConfigLogic)
    const { setSingular, setPlural, reset, save } = useActions(groupAnalyticsConfigLogic)

    const { groupsAccessStatus } = useValues(groupsAccessLogic)

    if (groupsAccessStatus !== GroupsAccessStatus.AlreadyUsing) {
        // Hide settings unless actually using the feature
        return null
    }

    const columns: LemonTableColumns<GroupType> = [
        {
            title: 'Group type',
            tooltip: 'As used in code',
            dataIndex: 'group_type',
            key: 'name',
            render: function RenderName(name) {
                return name
            },
        },
        {
            title: 'Singular name',
            key: 'singular',
            render: function Render(_, groupType) {
                return (
                    <LemonInput
                        value={
                            singularChanges[groupType.group_type_index] ||
                            groupType.name_singular ||
                            groupType.group_type
                        }
                        onChange={(e) => setSingular(groupType.group_type_index, e)}
                    />
                )
            },
        },
        {
            title: 'Plural name',
            key: 'plural',
            render: function Render(_, groupType) {
                return (
                    <LemonInput
                        value={
                            pluralChanges[groupType.group_type_index] ||
                            groupType.name_plural ||
                            `${groupType.group_type}(s)`
                        }
                        onChange={(e) => setPlural(groupType.group_type_index, e)}
                    />
                )
            },
        },
    ]

    return (
        <div id="group-analytics">
            <h2 className="subtitle">Group Analytics</h2>
            <p>
                This project has access to group analytics. Below you can configure how various group types are
                displayed throughout the app.
            </p>
            <LemonTable columns={columns} dataSource={groupTypes} loading={groupTypesLoading} />

            <div className="flex gap-2 mt-4">
                <LemonButton type="primary" disabled={!hasChanges} onClick={save}>
                    Save
                </LemonButton>
                <LemonButton disabled={!hasChanges} onClick={reset}>
                    Cancel
                </LemonButton>
            </div>
            <LemonDivider className="my-6" />
        </div>
    )
}
