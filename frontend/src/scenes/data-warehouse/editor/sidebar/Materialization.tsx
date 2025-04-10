import { Spinner } from '@posthog/lemon-ui'
import { useActions } from 'kea'
import { useValues } from 'kea'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { humanFriendlyDetailedTime } from 'lib/utils'
import { dataWarehouseViewsLogic } from 'scenes/data-warehouse/saved_queries/dataWarehouseViewsLogic'

import { DataWarehouseSyncInterval, OrNever } from '~/types'

import { multitabEditorLogic } from '../multitabEditorLogic'

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

export function Materialization(): JSX.Element {
    const { editingView } = useValues(multitabEditorLogic)
    const { runDataWarehouseSavedQuery, saveAsView } = useActions(multitabEditorLogic)

    const { dataWarehouseSavedQueryMapById, updatingDataWarehouseSavedQuery, initialDataWarehouseSavedQueryLoading } =
        useValues(dataWarehouseViewsLogic)
    const { updateDataWarehouseSavedQuery } = useActions(dataWarehouseViewsLogic)

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
                    <div className="flex flex-row items-center gap-2">
                        <h3 className="mb-0">Materialization</h3>
                        <LemonTag type="warning">BETA</LemonTag>
                        {savedQuery?.latest_error && savedQuery.status === 'Failed' && (
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
                                            savedQuery?.status === 'Running' || updatingDataWarehouseSavedQuery
                                                ? 'Query is already running'
                                                : false
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
                                        if (editingView) {
                                            updateDataWarehouseSavedQuery({
                                                id: editingView.id,
                                                sync_frequency: '24hour',
                                                types: [[]],
                                                lifecycle: 'create',
                                            })
                                        } else {
                                            saveAsView({ materializeAfterSave: true })
                                        }
                                    }}
                                    type="primary"
                                    loading={updatingDataWarehouseSavedQuery}
                                >
                                    {editingView ? 'Materialize' : 'Save and materialize'}
                                </LemonButton>
                            </div>
                        )}
                    </div>
                </div>
            </div>
        </div>
    )
}
