import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconPageChart, IconPencil, IconStopFilled, IconTrash } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { atColumn, createdAtColumn, createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { queryEndpointLogic } from 'scenes/data-warehouse/editor/output-pane-tabs/queryEndpointLogic'
import { urls } from 'scenes/urls'

import { QueryEndpointType } from '~/types'

import { EmbeddedTab } from '../common'
import { queryEndpointsLogic } from './queryEndpointsLogic'
import { OutputTab } from 'scenes/data-warehouse/editor/outputPaneLogic'

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
    const { deleteQueryEndpoint, deactivateQueryEndpoint } = useActions(queryEndpointLogic)

    const columns: LemonTableColumns<QueryEndpointType> = [
        {
            title: 'Name',
            key: 'name',
            dataIndex: 'name',
            width: '25%',
            render: function Render(_, record) {
                return (
                    <LemonTableLink
                        // TODO: Add link to endpoint modal
                        to={urls.embeddedAnalytics(EmbeddedTab.QUERY_ENDPOINTS)}
                        title={record.name}
                        description={record.description}
                    />
                )
            },
            sorter: (a: QueryEndpointType, b: QueryEndpointType) => a.name.localeCompare(b.name),
        },
        createdAtColumn<QueryEndpointType>() as LemonTableColumn<
            QueryEndpointType,
            keyof QueryEndpointType | undefined
        >,
        createdByColumn<QueryEndpointType>() as LemonTableColumn<
            QueryEndpointType,
            keyof QueryEndpointType | undefined
        >,
        atColumn<QueryEndpointType>('last_executed_at', 'Last executed at') as LemonTableColumn<
            QueryEndpointType,
            keyof QueryEndpointType | undefined
        >,
        {
            title: 'Endpoint path',
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
            title: 'Status',
            key: 'is_active',
            dataIndex: 'is_active',
            align: 'center',
            render: (_, record) => (
                <span>
                    {record.is_active ? (
                        <LemonTag type="success">Active</LemonTag>
                    ) : (
                        <LemonTag type="danger">Inactive</LemonTag>
                    )}
                </span>
            ),
            sorter: (a: QueryEndpointType, b: QueryEndpointType) => Number(b.is_active) - Number(a.is_active),
        },
        {
            key: 'actions',
            width: 0,
            render: (_, record) => (
                <More
                    overlay={
                        <>
                            <LemonButton
                                onClick={() => {
                                    router.actions.push(
                                        // TODO: Add request name to URL
                                        urls.embeddedAnalytics(EmbeddedTab.USAGE)
                                    )
                                }}
                                fullWidth
                            >
                                View usage
                            </LemonButton>

                            <LemonDivider />
                            <LemonButton
                                onClick={() => {
                                    deactivateQueryEndpoint(record.name)
                                }}
                                fullWidth
                                status="alt"
                            >
                                Deactivate query endpoint
                            </LemonButton>
                            <LemonButton
                                onClick={() => {
                                    deleteQueryEndpoint(record.name)
                                }}
                                fullWidth
                                status="danger"
                            >
                                Delete query endpoint
                            </LemonButton>
                        </>
                    }
                />
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
                data-attr="query-endpoints-table"
                pagination={{ pageSize: 20 }}
                dataSource={queryEndpoints as QueryEndpointType[]}
                rowKey="id"
                rowClassName={(record) => (record._highlight ? 'highlighted' : null)}
                columns={columns}
                loading={queryEndpointsLoading}
                // TODO: defaultSorting & onSort
                emptyState="No query endpoints matching your filters!"
                nouns={['query endpoint', 'query endpoints']}
            />
        </>
    )
}
