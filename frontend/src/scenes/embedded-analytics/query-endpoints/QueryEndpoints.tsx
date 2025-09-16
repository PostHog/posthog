import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useState } from 'react'

import { IconCode, IconPageChart, IconPencil } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
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
            title: 'Created At',
            key: 'created_at',
            dataIndex: 'created_at',
        },
        {
            title: 'Created By',
            key: 'created_by',
            dataIndex: 'created_by',
        },
        {
            title: 'URL',
            key: 'url',
            dataIndex: 'url',
        },
        {
            title: 'SQL',
            key: 'sql',
            align: 'center',
            dataIndex: 'sql',
            render: (_, record) => (
                <div className="flex justify-center">
                    <SQLButton sql={record.sql} />
                </div>
            ),
        },
        {
            title: 'Query Endpoint Usage',
            key: 'usage',
            align: 'center',
            render: (_, record) => (
                <div className="flex justify-center">
                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={<IconPageChart />}
                        onClick={() => {
                            router.actions.push(`/embedded-analytics?request_name=${encodeURIComponent(record.name)}`)
                        }}
                    />
                </div>
            ),
        },
        {
            title: 'Edit',
            key: 'edit',
            align: 'center',
            tooltip: 'Pushing to SQL Editor with a Query is not working properly.',
            render: (_, record) => (
                <div className="flex justify-center">
                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={<IconPencil />}
                        onClick={() => {
                            // TODO: Once editor is refactored, allow sending #output-pane-tab=query-endpoint
                            router.actions.push(urls.sqlEditor(record.sql))
                        }}
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
