import React from 'react'
import { useActions, useValues } from 'kea'
import { Group } from '~/types'
import { groupsListLogic } from './groupsListLogic'
import { PropertiesTable } from 'lib/components/PropertiesTable'
import { PersonPageHeader } from 'scenes/persons/PersonPageHeader'
import { LemonTableColumns } from 'lib/components/LemonTable/types'
import { TZLabel } from 'lib/components/TimezoneAware'
import { LemonTable } from 'lib/components/LemonTable/LemonTable'

export function Groups(): JSX.Element {
    const { groups, groupsLoading } = useValues(groupsListLogic)
    const { loadGroups } = useActions(groupsListLogic)

    const columns: LemonTableColumns<Group> = [
        {
            title: 'Key',
            key: 'group_key',
            render: function Render(_, group: Group) {
                return <>{group.group_key}</>
            },
        },
        {
            title: 'Last updated',
            key: 'created_at',
            render: function Render(_, group: Group) {
                return <TZLabel time={group.created_at} />
            },
        },
    ]

    return (
        <>
            <PersonPageHeader />
            <LemonTable
                columns={columns}
                rowKey="group_key"
                loading={groupsLoading}
                dataSource={groups.results}
                expandable={{
                    expandedRowRender: function RenderPropertiesTable({ group_properties }) {
                        return <PropertiesTable properties={group_properties} />
                    },
                    rowExpandable: ({ group_properties }) =>
                        !!group_properties && Object.keys(group_properties).length > 0,
                }}
                pagination={{
                    controlled: true,
                    onBackward: groups.previous_url
                        ? () => {
                              loadGroups(groups.previous_url)
                              window.scrollTo(0, 0)
                          }
                        : undefined,
                    onForward: groups.next_url
                        ? () => {
                              loadGroups(groups.next_url)
                              window.scrollTo(0, 0)
                          }
                        : undefined,
                }}
            />
        </>
    )
}
