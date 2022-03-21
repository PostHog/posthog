import React from 'react'
import { useActions, useValues } from 'kea'
import { GroupType } from '~/types'
import { LemonTable, LemonTableColumns } from 'lib/components/LemonTable'
import { Button, Divider, Input, Tooltip } from 'antd'
import { groupsAccessLogic, GroupsAccessStatus } from 'lib/introductions/groupsAccessLogic'
import { groupAnalyticsConfigLogic } from 'scenes/project/Settings/groupAnalyticsConfigLogic'
import { InfoCircleOutlined } from '@ant-design/icons'

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
            title: (
                <Tooltip title="As used in code">
                    Group type
                    <InfoCircleOutlined style={{ marginLeft: 6 }} />
                </Tooltip>
            ),
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
                    <Input
                        value={
                            singularChanges[groupType.group_type_index] ||
                            groupType.name_singular ||
                            groupType.group_type
                        }
                        onChange={(e) => setSingular(groupType.group_type_index, e.target.value)}
                    />
                )
            },
        },
        {
            title: 'Plural name',
            key: 'plural',
            render: function Render(_, groupType) {
                return (
                    <Input
                        value={
                            pluralChanges[groupType.group_type_index] ||
                            groupType.name_plural ||
                            `${groupType.group_type}(s)`
                        }
                        onChange={(e) => setPlural(groupType.group_type_index, e.target.value)}
                    />
                )
            },
        },
    ]

    return (
        <>
            <div id="group-analytics">
                <h2 className="subtitle" style={{ display: 'flex', alignItems: 'center' }}>
                    Group Analytics
                </h2>
                <p>
                    This project has access to group analytics. Below you can configure how various group types are
                    displayed throughout the app.
                </p>
                <LemonTable columns={columns} dataSource={groupTypes} loading={groupTypesLoading} />

                <div style={{ marginTop: 8 }}>
                    <Button type="primary" disabled={!hasChanges} onClick={save}>
                        Save
                    </Button>
                    <Button disabled={!hasChanges} onClick={reset}>
                        Cancel
                    </Button>
                </div>
            </div>

            <Divider />
        </>
    )
}
