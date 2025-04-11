import { LemonTable, Spinner } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { humanFriendlyDetailedTime } from 'lib/utils'
import { dataWarehouseViewsLogic } from 'scenes/data-warehouse/saved_queries/dataWarehouseViewsLogic'

import { multitabEditorLogic } from '../multitabEditorLogic'
import { infoTabLogic } from './infoTabLogic'

interface QueryInfoProps {
    codeEditorKey: string
}

export function QueryInfo({ codeEditorKey }: QueryInfoProps): JSX.Element {
    const { sourceTableItems } = useValues(infoTabLogic({ codeEditorKey: codeEditorKey }))
    const { editingView } = useValues(multitabEditorLogic)

    const { dataWarehouseSavedQueryMapById, initialDataWarehouseSavedQueryLoading } = useValues(dataWarehouseViewsLogic)

    // note: editingView is stale, but dataWarehouseSavedQueryMapById gets updated
    const savedQuery = editingView ? dataWarehouseSavedQueryMapById[editingView.id] : null

    if (initialDataWarehouseSavedQueryLoading) {
        return (
            <div className="w-full h-full flex items-center justify-center">
                <Spinner className="text-lg" />
            </div>
        )
    }

    return (
        <div className="overflow-auto">
            <div className="flex flex-col flex-1 p-4 gap-4">
                <div>
                    <h3>Columns</h3>
                    <p>Columns that are available in the materialized view.</p>
                </div>
                <LemonTable
                    columns={[
                        {
                            key: 'name',
                            title: 'Name',
                            render: (_, column) => column.name,
                        },
                        {
                            key: 'type',
                            title: 'Type',
                            render: (_, column) => column.type,
                        },
                        {
                            key: 'schema_valid',
                            title: 'Schema Valid',
                            render: (_, column) => (
                                <LemonTag type={column.schema_valid ? 'success' : 'danger'}>
                                    {column.schema_valid ? 'Yes' : 'No'}
                                </LemonTag>
                            ),
                        },
                    ]}
                    dataSource={savedQuery?.columns || []}
                />
                <div>
                    <h3>Dependencies</h3>
                    <p>
                        Dependencies are tables that this query uses. See when a source or materialized table was last
                        run.
                    </p>
                </div>
                <LemonTable
                    columns={[
                        {
                            key: 'Name',
                            title: 'Name',
                            render: (_, { name }) => name,
                        },
                        {
                            key: 'Type',
                            title: 'Type',
                            render: (_, { type }) => type,
                        },
                        {
                            key: 'Status',
                            title: 'Status',
                            render: (_, { type, status }) => {
                                if (type === 'source') {
                                    return (
                                        <Tooltip title="This is a source table, so it doesn't have a status">
                                            <span className="text-secondary">N/A</span>
                                        </Tooltip>
                                    )
                                }
                                return status
                            },
                        },
                        {
                            key: 'Last run at',
                            title: 'Last run at',
                            render: (_, { type, last_run_at }) => {
                                if (type === 'source') {
                                    return (
                                        <Tooltip title="This is a source table, so it is never run">
                                            <span className="text-secondary">N/A</span>
                                        </Tooltip>
                                    )
                                }
                                return humanFriendlyDetailedTime(last_run_at)
                            },
                        },
                    ]}
                    dataSource={sourceTableItems}
                />
            </div>
        </div>
    )
}
