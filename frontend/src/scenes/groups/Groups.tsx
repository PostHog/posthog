import React from 'react'
import { useActions, useValues } from 'kea'
import { Group } from '~/types'
import { groupsListLogic } from './groupsListLogic'
import { PropertiesTable } from 'lib/components/PropertiesTable'
import { PersonPageHeader } from 'scenes/persons/PersonPageHeader'
import { LemonTableColumns } from 'lib/components/LemonTable/types'
import { TZLabel } from 'lib/components/TimezoneAware'
import { LemonTable } from 'lib/components/LemonTable'
import { Link } from 'lib/components/Link'
import { urls } from 'scenes/urls'
import { SceneExport } from 'scenes/sceneTypes'

export const scene: SceneExport = {
    component: Groups,
    logic: groupsListLogic,
}

export function Groups(): JSX.Element {
    const { groups, groupsLoading } = useValues(groupsListLogic)
    const { loadGroups } = useActions(groupsListLogic)

    const columns: LemonTableColumns<Group> = [
        {
            title: 'Key',
            key: 'group_key',
            render: function Render(_, group: Group) {
                return (
                    <Link to={urls.group(group.group_type_index.toString(), group.group_key)}>{group.group_key}</Link>
                )
            },
        },
        {
            title: 'First seen',
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
                    onBackward: groups.previous
                        ? () => {
                              loadGroups(groups.previous)
                              window.scrollTo(0, 0)
                          }
                        : undefined,
                    onForward: groups.next
                        ? () => {
                              loadGroups(groups.next)
                              window.scrollTo(0, 0)
                          }
                        : undefined,
                }}
            />
        </>
    )
}
