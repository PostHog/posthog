import { LemonButton, LemonTable, LemonTag, LemonTagType } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { sourceWizardLogic } from 'scenes/data-warehouse/new/sourceWizardLogic'
import { dataWarehouseSettingsLogic } from 'scenes/data-warehouse/settings/dataWarehouseSettingsLogic'
import { urls } from 'scenes/urls'

import { DataTableNode, NodeKind } from '~/queries/schema'
import { ExternalDataSourceSchema } from '~/types'

export const SyncProgressStep = (): JSX.Element => {
    const { sourceId } = useValues(sourceWizardLogic)
    const { cancelWizard } = useActions(sourceWizardLogic)
    const { dataWarehouseSources, dataWarehouseSourcesLoading } = useValues(dataWarehouseSettingsLogic)

    const source = dataWarehouseSources?.results.find((n) => n.id === sourceId)
    const schemas = source?.schemas ?? []

    const getSyncStatus = (schema: ExternalDataSourceSchema): { status: string; tagType: LemonTagType } => {
        if (!schema.should_sync) {
            return {
                status: 'Not synced',
                tagType: 'default',
            }
        }

        if (schema.status === 'Running') {
            return {
                status: 'Syncing...',
                tagType: 'primary',
            }
        }

        if (schema.status === 'Completed') {
            return {
                status: 'Completed',
                tagType: 'success',
            }
        }

        return {
            status: 'Error',
            tagType: 'danger',
        }
    }

    return (
        <div className="flex flex-col gap-2">
            <div>
                <LemonTable
                    emptyState="No schemas selected"
                    dataSource={schemas}
                    loading={dataWarehouseSourcesLoading}
                    disableTableWhileLoading={false}
                    columns={[
                        {
                            title: 'Table',
                            key: 'table',
                            render: function RenderTable(_, schema) {
                                return schema.name
                            },
                        },
                        {
                            title: 'Status',
                            key: 'status',
                            render: function RenderStatus(_, schema) {
                                const { status, tagType } = getSyncStatus(schema)

                                return <LemonTag type={tagType}>{status}</LemonTag>
                            },
                        },
                        {
                            key: 'actions',
                            width: 0,
                            render: function RenderStatus(_, schema) {
                                if (schema.table && schema.status === 'Completed') {
                                    const query: DataTableNode = {
                                        kind: NodeKind.DataTableNode,
                                        full: true,
                                        source: {
                                            kind: NodeKind.HogQLQuery,
                                            query: `SELECT ${schema.table.columns
                                                .filter(
                                                    ({ table, fields, chain, schema_valid }) =>
                                                        !table && !fields && !chain && schema_valid
                                                )
                                                .map(({ name }) => name)} FROM ${
                                                schema.table.name === 'numbers' ? 'numbers(0, 10)' : schema.table.name
                                            } LIMIT 100`,
                                        },
                                    }
                                    return (
                                        <LemonButton
                                            className="my-1"
                                            type="primary"
                                            onClick={() => cancelWizard()}
                                            to={urls.insightNew(undefined, undefined, JSON.stringify(query))}
                                        >
                                            Query
                                        </LemonButton>
                                    )
                                }

                                return ''
                            },
                        },
                    ]}
                />
            </div>
        </div>
    )
}
