import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useState } from 'react'

import { IconCode, IconPageChart, IconPencil } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { Popover } from 'lib/lemon-ui/Popover'
import { urls } from 'scenes/urls'

import { QueryEndpointType } from '~/types'

import { queryEndpointsLogic } from './queryEndpointsLogic'

const SQLButton = ({ sql }: { sql: string }): JSX.Element => {
    const [popoverVisible, setPopoverVisible] = useState(false)

    return (
        <Popover
            visible={popoverVisible}
            onMouseEnterInside={() => setPopoverVisible(true)}
            onMouseLeaveInside={() => setPopoverVisible(false)}
            overlay={
                <div className="p-2 max-w-md">
                    <div className="text-sm font-medium mb-2">SQL Query</div>
                    <pre className="text-xs bg-gray-100 p-2 rounded overflow-x-auto whitespace-pre-wrap">{sql}</pre>
                </div>
            }
            placement="top"
        >
            <div onMouseEnter={() => setPopoverVisible(true)} onMouseLeave={() => setPopoverVisible(false)}>
                <LemonButton type="secondary" size="small" icon={<IconCode />} />
            </div>
        </Popover>
    )
}

export function QueryEndpoints(): JSX.Element {
    return (
        <>
            <QueryEndpointsTable />
        </>
    )
}

export const QueryEndpointsTable = (): JSX.Element => {
    const { setFilters } = useActions(queryEndpointsLogic)
    const { filters } = useValues(queryEndpointsLogic)
    const { queryEndpoints, queryEndpointsLoading } = useValues(queryEndpointsLogic)

    const columns: LemonTableColumns<QueryEndpointType> = [
        {
            title: 'Name',
            key: 'name',
            dataIndex: 'name',
        },
        {
            title: 'Description',
            key: 'description',
            dataIndex: 'description',
        },
        {
            title: 'Status',
            key: 'is_active',
            dataIndex: 'is_active',
            render: (_, record) => (
                <span>
                    {record.is_active ? (
                        <LemonTag type="success">Active</LemonTag>
                    ) : (
                        <LemonTag type="danger">Inactive</LemonTag>
                    )}
                </span>
            ),
        },
        {
            title: 'Created At',
            key: 'created_at',
            dataIndex: 'created_at',
            render: (_, record) => new Date(record.created_at).toLocaleDateString(),
        },
        {
            title: 'Created By',
            key: 'created_by',
            dataIndex: 'created_by',
            render: (_, record) =>
                record.created_by
                    ? `${record.created_by.first_name} ${record.created_by.last_name}`.trim() || record.created_by.email
                    : 'Unknown',
        },
        {
            title: 'Endpoint Path',
            key: 'endpoint_path',
            dataIndex: 'endpoint_path',
            render: (_, record) => (
                <LemonButton
                    type="secondary"
                    size="small"
                    onClick={() => {
                        navigator.clipboard.writeText(record.endpoint_path)
                        lemonToast.success('Endpoint URL copied to clipboard')
                    }}
                    className="font-mono text-xs"
                >
                    {record.endpoint_path}
                </LemonButton>
            ),
        },
        {
            title: 'Actions',
            key: 'actions',
            width: 0,
            render: (_, record) => (
                <div className="flex items-center gap-2">
                    <SQLButton sql={record.query.query} />
                    <More
                        overlay={
                            <>
                                <LemonButton
                                    icon={<IconPageChart />}
                                    onClick={() => {
                                        router.actions.push(
                                            `/embedded-analytics?request_name=${encodeURIComponent(record.name)}`
                                        )
                                    }}
                                    fullWidth
                                >
                                    View Usage
                                </LemonButton>

                                <LemonButton
                                    icon={<IconPencil />}
                                    onClick={() => {
                                        // TODO: Once editor is refactored, allow sending #output-pane-tab=query-endpoint
                                        router.actions.push(urls.sqlEditor(record.query.query))
                                    }}
                                    fullWidth
                                >
                                    Edit Query
                                </LemonButton>
                            </>
                        }
                    />
                </div>
            ),
        },
    ]

    return (
        <>
            <div className="flex justify-between gap-2 flex-wrap mb-4">
                <LemonInput
                    type="search"
                    className="w-1/3"
                    placeholder="Search for query endpoints"
                    onChange={(x) => setFilters({ search: x })}
                    value={filters.search}
                />
            </div>
            <LemonTable
                dataSource={queryEndpoints as QueryEndpointType[]}
                loading={queryEndpointsLoading}
                rowKey="id"
                stealth={true}
                rowClassName={(record) => (record._highlight ? 'highlighted' : null)}
                emptyState="No query endpoints matching your filters!"
                nouns={['query endpoint', 'query endpoints']}
                columns={columns}
            />
        </>
    )
}
