import { LemonButton, LemonSelect, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { DataWarehouseSourceIcon } from 'scenes/data-warehouse/settings/DataWarehouseSourceIcon'
import { urls } from 'scenes/urls'

import { MARKETING_ANALYTICS_SCHEMA } from '~/queries/schema/schema-general'
import { ExternalDataSource, PipelineNodeTab, PipelineStage } from '~/types'

import { marketingAnalyticsSettingsLogic } from '../../logic/marketingAnalyticsSettingsLogic'

const VALID_MARKETING_SOURCES: ExternalDataSource['source_type'][] = ['BigQuery']

type SimpleDataWarehouseTable = {
    name: string
    source_type: ExternalDataSource['source_type']
    id: string
    source_id: string
    source_prefix: string
    columns?: { name: string; type: string }[]
}

export function NonNativeExternalDataSourceConfiguration({
    buttonRef,
}: {
    buttonRef?: React.RefObject<HTMLButtonElement>
}): JSX.Element {
    const { dataWarehouseSources, sources } = useValues(marketingAnalyticsSettingsLogic)
    const { updateSourceMapping } = useActions(marketingAnalyticsSettingsLogic)
    const marketingSources =
        dataWarehouseSources?.results.filter((source) => VALID_MARKETING_SOURCES.includes(source.source_type)) ?? []

    const tables = marketingSources
        .map((source) =>
            source.schemas.map((schema) => ({
                ...schema,
                source_type: source.source_type,
                source_id: source.id,
                source_prefix: source.prefix,
                columns: schema.table?.columns || [],
            }))
        )
        .flat()

    const isColumnTypeCompatible = (columnType: string, schemaFieldTypes: string[]): boolean => {
        return schemaFieldTypes.includes(columnType)
    }

    const renderColumnMappingDropdown = (
        table: SimpleDataWarehouseTable,
        fieldName: keyof typeof MARKETING_ANALYTICS_SCHEMA
    ): JSX.Element => {
        const sourceMapping = sources?.[table.id]
        const currentMapping = sourceMapping?.[fieldName]

        // Get the expected type from the schema
        const expectedTypes = MARKETING_ANALYTICS_SCHEMA[fieldName]

        // Filter columns based on type compatibility
        const compatibleColumns =
            table.columns?.filter((col) => isColumnTypeCompatible(col.type, expectedTypes as unknown as string[])) || []

        const columnOptions = [
            { label: 'None', value: null as string | null },
            ...compatibleColumns.map((col) => ({
                label: `${col.name} (${col.type})`,
                value: col.name as string | null,
            })),
        ]

        return (
            <LemonSelect
                value={currentMapping || null}
                onChange={(value) => updateSourceMapping(table.id, fieldName, value || undefined)}
                options={columnOptions}
                placeholder="Select column..."
                size="small"
            />
        )
    }

    return (
        <div>
            <h3 className="mb-2">Non Native Data Warehouse Sources Configuration</h3>
            <p className="mb-4">
                PostHog can display marketing data in our Marketing Analytics product from the following data warehouse
                sources.
            </p>
            <LemonTable
                rowKey={(item) => item.id}
                loading={dataWarehouseSources === null}
                dataSource={tables}
                columns={[
                    {
                        key: 'source_icon',
                        title: '',
                        width: 0,
                        render: (_, item: any) => {
                            return <DataWarehouseSourceIcon type={item.source_type} />
                        },
                    },
                    {
                        key: 'source',
                        title: 'Source',
                        width: 0,
                        render: (_, item: any) => {
                            return (
                                <Link
                                    to={urls.pipelineNode(
                                        PipelineStage.Source,
                                        `managed-${item.source_id}`,
                                        PipelineNodeTab.Schemas
                                    )}
                                >
                                    {item.source_type} {item.source_prefix}
                                </Link>
                            )
                        },
                    },
                    {
                        key: 'prefix',
                        title: 'Table',
                        render: (_, item: any) => item.name,
                    },
                    ...Object.keys(MARKETING_ANALYTICS_SCHEMA).map((column) => ({
                        key: column,
                        title: column.replace(/_/g, ' ').replace(/\b\w/g, (l) => l.toUpperCase()),
                        render: (_: any, item: any) =>
                            renderColumnMappingDropdown(item, column as keyof typeof MARKETING_ANALYTICS_SCHEMA),
                    })),
                    {
                        key: 'actions',
                        width: 0,
                        title: (
                            <LemonButton
                                className="my-1"
                                ref={buttonRef}
                                type="primary"
                                onClick={() => {
                                    router.actions.push(urls.pipelineNodeNew(PipelineStage.Source))
                                }}
                            >
                                Add new source
                            </LemonButton>
                        ),
                        render: () => null,
                    },
                ]}
            />
        </div>
    )
}
