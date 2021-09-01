import { Table } from 'antd'
import { useValues } from 'kea'
import React from 'react'
import { PageHeader } from '../../lib/components/PageHeader'
import { groupsLogic } from './groupsLogic'

export function GroupTypes(): JSX.Element {
    const { currentGroupType, groups } = useValues(groupsLogic)

    return (
        <div style={{ marginBottom: 128 }}>
            <PageHeader
                title={
                    <>
                        Groups – <code>{currentGroupType}</code>
                    </>
                }
            />
            <Table
                rowKey="id"
                columns={[
                    {
                        dataIndex: 'id',
                        title: 'ID',
                    },
                ]}
                dataSource={groups}
            />
        </div>
    )
}
