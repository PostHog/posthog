import { LemonButton, LemonSelect, LemonTag, Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { humanFriendlyDetailedTime } from 'lib/utils'
import TabScroller from 'scenes/data-warehouse/editor/OutputPaneTabs/TabScroller'
import { dataWarehouseViewsLogic } from 'scenes/data-warehouse/saved_queries/dataWarehouseViewsLogic'

import { DataWarehouseSyncInterval, OrNever } from '~/types'

import { multitabEditorLogic } from '../multitabEditorLogic'
import { infoTabLogic } from './infoTabLogic'

interface InfoTabProps {
    codeEditorKey: string
}

const OPTIONS = [
    {
        value: 'never' as OrNever,
        label: ' No resync',
    },
    {
        value: '5min' as DataWarehouseSyncInterval,
        label: ' Resync every 5 mins',
    },
    {
        value: '30min' as DataWarehouseSyncInterval,
        label: ' Resync every 30 mins',
    },
    {
        value: '1hour' as DataWarehouseSyncInterval,
        label: ' Resync every 1 hour',
    },
    {
        value: '6hour' as DataWarehouseSyncInterval,
        label: ' Resync every 6 hours',
    },
    {
        value: '12hour' as DataWarehouseSyncInterval,
        label: ' Resync every 12 hours',
    },
    {
        value: '24hour' as DataWarehouseSyncInterval,
        label: ' Resync Daily',
    },
    {
        value: '7day' as DataWarehouseSyncInterval,
        label: ' Resync Weekly',
    },
    {
        value: '30day' as DataWarehouseSyncInterval,
        label: ' Resync Monthly',
    },
]

export function InfoTab({ codeEditorKey }: InfoTabProps): JSX.Element {
    const { sourceTableItems } = useValues(infoTabLogic({ codeEditorKey: codeEditorKey }))
    const { editingView } = useValues(multitabEditorLogic)
    const { runDataWarehouseSavedQuery } = useActions(multitabEditorLogic)

    const { dataWarehouseSavedQueryMapById, updatingDataWarehouseSavedQuery } = useValues(dataWarehouseViewsLogic)
    const { updateDataWarehouseSavedQuery } = useActions(dataWarehouseViewsLogic)

    // note: editingView is stale, but dataWarehouseSavedQueryMapById gets updated
    const savedQuery = editingView ? dataWarehouseSavedQueryMapById[editingView.id] : null

    return (
        <TabScroller>
            <div className="flex flex-col flex-1 p-4 gap-4">
                <div>
                    <div className="flex flex-row items-center gap-2">
                        <h3 className="mb-0">Materialization</h3>
                        <LemonTag type="warning">BETA</LemonTag>
                        {savedQuery?.latest_error && (
                            <Tooltip title={savedQuery.latest_error}>
                                <LemonTag type="danger">Error</LemonTag>
                            </Tooltip>
                        )}
                    </div>
                    <div>
                        {savedQuery?.sync_frequency || savedQuery?.last_run_at ? (
                            <div>
                                {savedQuery?.last_run_at ? (
                                    `Last run at ${humanFriendlyDetailedTime(savedQuery?.last_run_at)}`
                                ) : (
                                    <div>
                                        <span>Materialization scheduled</span>
                                    </div>
                                )}
                                <div className="flex gap-4 mt-2">
                                    <LemonButton
                                        loading={savedQuery?.status === 'Running'}
                                        disabledReason={
                                            savedQuery?.status === 'Running' ? 'Query is already running' : false
                                        }
                                        onClick={() => editingView && runDataWarehouseSavedQuery(editingView.id)}
                                        type="secondary"
                                    >
                                        Sync now
                                    </LemonButton>
                                    <LemonSelect
                                        className="h-9"
                                        disabledReason={
                                            savedQuery?.status === 'Running' ? 'Query is already running' : false
                                        }
                                        value={
                                            editingView
                                                ? dataWarehouseSavedQueryMapById[editingView.id]?.sync_frequency ||
                                                  'never'
                                                : 'never'
                                        }
                                        onChange={(newValue) => {
                                            if (editingView && newValue) {
                                                updateDataWarehouseSavedQuery({
                                                    id: editingView.id,
                                                    sync_frequency: newValue,
                                                    types: [[]],
                                                    lifecycle: 'update',
                                                })
                                            }
                                        }}
                                        loading={updatingDataWarehouseSavedQuery}
                                        options={OPTIONS}
                                    />
                                </div>
                            </div>
                        ) : (
                            <div>
                                <p>
                                    Materialized views are a way to pre-compute data in your data warehouse. This allows
                                    you to run queries faster and more efficiently.
                                </p>
                                <LemonButton
                                    onClick={() => {
                                        return (
                                            editingView &&
                                            updateDataWarehouseSavedQuery({
                                                id: editingView.id,
                                                sync_frequency: '24hour',
                                                types: [[]],
                                                lifecycle: 'create',
                                            })
                                        )
                                    }}
                                    type="primary"
                                    disabledReason={editingView ? undefined : 'You must save the view first'}
                                    loading={updatingDataWarehouseSavedQuery}
                                >
                                    Materialize
                                </LemonButton>
                            </div>
                        )}
                    </div>
                </div>
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
        </TabScroller>
    )
}
