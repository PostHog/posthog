import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconWarning } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonTable,
    LemonTableColumns,
    LemonTag,
    LemonTagType,
    Link,
    Tooltip,
} from '@posthog/lemon-ui'

import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { ExternalDataSourceSchema } from '~/types'

import { buildTableQueryUrl } from 'products/data_warehouse/frontend/utils'

import { sourceWizardLogic } from '../../../scenes/NewSourceScene/sourceWizardLogic'
import { sourceManagementLogic } from '../../logics/sourceManagementLogic'

export function getSourceAccessMethod(
    wizardAccessMethod: 'warehouse' | 'direct',
    sourceAccessMethod?: 'warehouse' | 'direct'
): 'warehouse' | 'direct' {
    return sourceAccessMethod ?? wizardAccessMethod
}

export function getPreviewQueryUrl(
    tableName: string,
    accessMethod: 'warehouse' | 'direct' | undefined,
    sourceId?: string | null
): string {
    return buildTableQueryUrl(tableName, accessMethod === 'direct' ? (sourceId ?? undefined) : undefined)
}

export const SyncProgressStep = (): JSX.Element => {
    const { sourceId, isWrapped, source: wizardSource } = useValues(sourceWizardLogic)
    const { cancelWizard } = useActions(sourceWizardLogic)
    const { dataWarehouseSources, dataWarehouseSourcesLoading } = useValues(sourceManagementLogic)
    const source = dataWarehouseSources?.results.find((n) => n.id === sourceId)
    const schemas = source?.schemas ?? []
    const sourceAccessMethod = getSourceAccessMethod(wizardSource.access_method, source?.access_method)
    const isDirectQuerySource = sourceAccessMethod === 'direct'

    const getSyncStatus = (schema: ExternalDataSourceSchema): { status: string; tagType: LemonTagType } => {
        if (isDirectQuerySource) {
            return schema.should_sync
                ? { status: 'Enabled', tagType: 'success' }
                : { status: 'Hidden', tagType: 'default' }
        }

        if (!schema.should_sync) {
            return {
                status: 'Not synced',
                tagType: 'default',
            }
        }

        if (!schema.status || schema.status === 'Running') {
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

        if (schema.status === 'Paused') {
            return {
                status: 'Paused',
                tagType: 'default',
            }
        }

        if (schema.status === 'Cancelled') {
            return {
                status: 'Cancelled',
                tagType: 'default',
            }
        }

        return {
            status: 'Error',
            tagType: 'danger',
        }
    }

    const columns: LemonTableColumns<ExternalDataSourceSchema> = [
        {
            title: 'Table',
            key: 'table',
            render: function RenderTable(_, schema) {
                if (!schema.table) {
                    return schema.label ?? schema.name
                }

                return (
                    <Link
                        to={getPreviewQueryUrl(schema.table.name, sourceAccessMethod, sourceId)}
                        onClick={() => cancelWizard()}
                    >
                        {schema.label ?? schema.name}
                    </Link>
                )
            },
        },
        {
            title: 'Status',
            key: 'status',
            render: function RenderStatus(_, schema) {
                const { status, tagType } = getSyncStatus(schema)

                if (tagType === 'danger' && schema.latest_error) {
                    return (
                        <Tooltip title={schema.latest_error}>
                            <span className="inline-flex items-center gap-1">
                                <LemonTag type={tagType}>
                                    <IconWarning className="mr-1" />
                                    {status}
                                </LemonTag>
                            </span>
                        </Tooltip>
                    )
                }

                return <LemonTag type={tagType}>{status}</LemonTag>
            },
        },
    ]

    if (!isWrapped) {
        columns.push({
            key: 'actions',
            width: 0,
            render: function RenderStatus(_, schema) {
                const table = schema.table

                if (table && (isDirectQuerySource || schema.status === 'Completed')) {
                    return (
                        <LemonButton
                            className="my-1"
                            type="primary"
                            onClick={() => {
                                const previewUrl = getPreviewQueryUrl(table.name, sourceAccessMethod, sourceId)
                                cancelWizard()
                                router.actions.push(previewUrl)
                            }}
                        >
                            Query
                        </LemonButton>
                    )
                }

                return ''
            },
        })
    }

    const schemasWithErrors = schemas.filter(
        (schema) =>
            schema.should_sync && schema.status !== 'Running' && schema.status !== 'Completed' && schema.latest_error
    )

    return (
        <SceneSection
            title={
                isDirectQuerySource
                    ? "You're all set! Your enabled tables are now available in the SQL editor."
                    : "You're all set! We'll import the data in the background, and after it's done, you will be able to query it in PostHog."
            }
        >
            {schemasWithErrors.length > 0 && (
                <LemonBanner type="warning" className="mb-4">
                    <p className="font-semibold mb-1">
                        {schemasWithErrors.length === 1
                            ? '1 table failed to sync'
                            : `${schemasWithErrors.length} tables failed to sync`}
                    </p>
                    <p className="text-sm">
                        Syncs will be retried automatically. You can continue setup — the remaining tables will keep
                        syncing in the background. Hover over the error status for details.
                    </p>
                </LemonBanner>
            )}
            <LemonTable
                emptyState="No schemas selected"
                dataSource={schemas}
                loading={dataWarehouseSourcesLoading}
                disableTableWhileLoading={false}
                columns={columns}
            />
        </SceneSection>
    )
}
