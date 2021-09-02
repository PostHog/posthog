import { Table } from 'antd'
import { useValues } from 'kea'
import { ResizableColumnType } from 'lib/components/ResizableTable'
import React from 'react'
import { Group } from '~/types'
import { groupsLogic } from './groupsLogic'

export function GroupsTable({ columns }: { columns: ResizableColumnType<Partial<Group>>[] }): JSX.Element {
    const { currentGroupType, groups } = useValues(groupsLogic)

    return (
        <Table
            size="small"
            columns={columns}
            rowKey={currentGroupType || ''}
            pagination={{ pageSize: 99999, hideOnSinglePage: true }}
            dataSource={groups}
            key={currentGroupType}
            className="persons-table"
        />
    )
}
