import { LemonButton, LemonTag, Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { humanFriendlyDetailedTime } from 'lib/utils'

import { multitabEditorLogic } from '../multitabEditorLogic'
import { infoTabLogic } from './infoTabLogic'

interface InfoTabProps {
    codeEditorKey: string
}

export function InfoTab({ codeEditorKey }: InfoTabProps): JSX.Element {
    const { sourceTableItems } = useValues(infoTabLogic({ codeEditorKey: codeEditorKey }))
    const { editingView, isEditingMaterializedView } = useValues(multitabEditorLogic)
    const { runDataWarehouseSavedQuery } = useActions(multitabEditorLogic)

    return (
        <div className="flex flex-col flex-1 m-4 gap-4">
            <div>
                <div className="flex flex-row items-center gap-2">
                    <h3 className="mb-0">Materialization</h3>
                    <LemonTag type="warning">BETA</LemonTag>
                </div>
                <div>
                    {isEditingMaterializedView ? (
                        <div>
                            {editingView?.last_run_at ? (
                                `Last run at ${humanFriendlyDetailedTime(editingView.last_run_at)}`
                            ) : (
                                <div>
                                    <span>Materialization scheduled</span>
                                </div>
                            )}
                            <LemonButton
                                onClick={() => editingView && runDataWarehouseSavedQuery(editingView.id)}
                                className="mt-2"
                                type="secondary"
                            >
                                Run now
                            </LemonButton>
                        </div>
                    ) : (
                        <div>
                            <p>
                                Materialized views are a way to pre-compute data in your data warehouse. This allows you
                                to run queries faster and more efficiently.
                            </p>
                            <LemonButton
                                onClick={() => editingView && runDataWarehouseSavedQuery(editingView.id)}
                                type="primary"
                                disabledReason={editingView ? undefined : 'You must save the view first'}
                            >
                                Materialize
                            </LemonButton>
                        </div>
                    )}
                </div>
            </div>
            <div>
                <h3>Dependencies</h3>
                <p>
                    Dependencies are tables that this query uses. See when a source or materialized table was last run.
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
                                        <span className="text-muted">N/A</span>
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
                                        <span className="text-muted">N/A</span>
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
    )
}
