import { LemonTable, LemonTag, LemonTagType } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { sourceWizardLogic } from 'scenes/data-warehouse/new/sourceWizardLogic'
import { dataWarehouseSettingsLogic } from 'scenes/data-warehouse/settings/dataWarehouseSettingsLogic'

export const SyncProgressStep = (): JSX.Element => {
    const { databaseSchema, sourceId } = useValues(sourceWizardLogic)
    const { dataWarehouseSources, dataWarehouseSourcesLoading } = useValues(dataWarehouseSettingsLogic)

    const source = dataWarehouseSources?.results.find((n) => n.id === sourceId)

    const getSyncStatus = (shouldSync: boolean): { status: string; tagType: LemonTagType } => {
        if (!shouldSync) {
            return {
                status: 'Not synced',
                tagType: 'default',
            }
        }

        if (!source || source.status === 'Running') {
            return {
                status: 'Syncing...',
                tagType: 'primary',
            }
        }

        if (source.status === 'Completed') {
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
                    dataSource={databaseSchema}
                    loading={dataWarehouseSourcesLoading}
                    disableTableWhileLoading={false}
                    columns={[
                        {
                            title: 'Table',
                            key: 'table',
                            render: function RenderTable(_, schema) {
                                return schema.table
                            },
                        },
                        {
                            title: 'Status',
                            key: 'status',
                            render: function RenderStatus(_, schema) {
                                const { status, tagType } = getSyncStatus(schema.should_sync)

                                return <LemonTag type={tagType}>{status}</LemonTag>
                            },
                        },
                    ]}
                />
            </div>
        </div>
    )
}
