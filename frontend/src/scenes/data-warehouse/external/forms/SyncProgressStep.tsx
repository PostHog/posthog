import { LemonTable, LemonTag, LemonTagType } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { sourceWizardLogic } from 'scenes/data-warehouse/new/sourceWizardLogic'
import { dataWarehouseSettingsLogic } from 'scenes/data-warehouse/settings/dataWarehouseSettingsLogic'

import { ExternalDataSourceSchema } from '~/types'

export const SyncProgressStep = (): JSX.Element => {
    const { sourceId } = useValues(sourceWizardLogic)
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
                    ]}
                />
            </div>
        </div>
    )
}
