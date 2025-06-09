import { IconCheck, IconPlus, IconWarning, IconX } from '@posthog/icons'
import { LemonButton, LemonDropdown, Link, Tooltip } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { router } from 'kea-router'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { dataWarehouseSettingsLogic } from 'scenes/data-warehouse/settings/dataWarehouseSettingsLogic'
import { DataWarehouseSourceIcon } from 'scenes/data-warehouse/settings/DataWarehouseSourceIcon'
import { urls } from 'scenes/urls'

import { ExternalDataSource, PipelineNodeTab, PipelineStage } from '~/types'

const VALID_MARKETING_SOURCES: ExternalDataSource['source_type'][] = ['GoogleAds', 'MetaAds']
const NEEDED_FIELDS_FOR_MARKETING_ANALYTICS: string[] = [
    'ad',
    'campaign',
    'ad_group_ad',
    'ad_group_criterion',
    'customer',
]

export function NativeExternalDataSourceConfiguration(): JSX.Element {
    const { dataWarehouseSources } = useValues(dataWarehouseSettingsLogic)

    const marketingSources =
        dataWarehouseSources?.results.filter((source) => VALID_MARKETING_SOURCES.includes(source.source_type)) ?? []

    const getSourceStatus = (source: ExternalDataSource): { isConfigured: boolean; message: string } => {
        if (!source.schemas || source.schemas.length === 0) {
            return { isConfigured: false, message: 'No schemas configured' }
        }

        const neededFieldsWithSync = NEEDED_FIELDS_FOR_MARKETING_ANALYTICS.filter((field) => {
            const schema = source.schemas.find((schema) => schema.name === field)
            return schema && schema.should_sync
        })

        if (neededFieldsWithSync.length === NEEDED_FIELDS_FOR_MARKETING_ANALYTICS.length) {
            return { isConfigured: true, message: 'Ready to use! All required fields are syncing.' }
        }

        const missingCount = NEEDED_FIELDS_FOR_MARKETING_ANALYTICS.length - neededFieldsWithSync.length
        return {
            isConfigured: false,
            message: `${missingCount} field${
                missingCount > 1 ? 's' : ''
            } need to be synced: ${NEEDED_FIELDS_FOR_MARKETING_ANALYTICS.filter(
                (field) => !neededFieldsWithSync.includes(field)
            ).join(', ')}`,
        }
    }

    return (
        <div>
            <h3 className="mb-2">Native Data Warehouse Sources Configuration</h3>
            <p className="mb-4">
                PostHog can display marketing data in our Marketing Analytics product from the following data warehouse
                sources.
            </p>
            <LemonTable
                rowKey={(item) => item.id}
                loading={dataWarehouseSources === null}
                dataSource={marketingSources}
                columns={[
                    {
                        key: 'source',
                        title: '',
                        width: 0,
                        render: (_, item: ExternalDataSource) => {
                            return <DataWarehouseSourceIcon type={item.source_type} />
                        },
                    },
                    {
                        key: 'prefix',
                        title: 'Source',
                        render: (_, item: ExternalDataSource) => {
                            return (
                                <Link
                                    to={urls.pipelineNode(
                                        PipelineStage.Source,
                                        `managed-${item.id}`,
                                        PipelineNodeTab.Schemas
                                    )}
                                >
                                    {item.prefix || item.source_type}
                                </Link>
                            )
                        },
                    },
                    {
                        key: 'status',
                        title: 'Status',
                        width: 80,
                        render: (_, item: ExternalDataSource) => {
                            const { isConfigured, message } = getSourceStatus(item)

                            if (isConfigured) {
                                return (
                                    <Tooltip title={message}>
                                        <div className="flex justify-center">
                                            <IconCheck className="text-success text-lg" />
                                        </div>
                                    </Tooltip>
                                )
                            }
                            const hasAnySchemas = item.schemas && item.schemas.length > 0
                            return (
                                <Tooltip title={message}>
                                    <div className="flex justify-center">
                                        {hasAnySchemas ? (
                                            <IconWarning className="text-warning text-lg" />
                                        ) : (
                                            <IconX className="text-muted text-lg" />
                                        )}
                                    </div>
                                </Tooltip>
                            )
                        },
                    },
                    {
                        key: 'actions',
                        width: 0,
                        title: (
                            <LemonDropdown
                                className="my-1"
                                overlay={
                                    <div className="p-1">
                                        {VALID_MARKETING_SOURCES.map((source) => (
                                            <LemonButton
                                                key={source}
                                                onClick={() => {
                                                    router.actions.push(
                                                        urls.pipelineNodeNew(PipelineStage.Source, { source })
                                                    )
                                                }}
                                                fullWidth
                                                size="small"
                                            >
                                                <div className="flex items-center gap-2">
                                                    <DataWarehouseSourceIcon type={source} />
                                                    {source}
                                                    <IconPlus className="text-muted" />
                                                </div>
                                            </LemonButton>
                                        ))}
                                    </div>
                                }
                            >
                                <LemonButton type="primary" size="small">
                                    Add new source
                                </LemonButton>
                            </LemonDropdown>
                        ),
                        render: () => null,
                    },
                ]}
            />
        </div>
    )
}
