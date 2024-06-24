import { TZLabel } from '@posthog/apps-common'
import {
    LemonButton,
    LemonDialog,
    LemonModal,
    LemonSelect,
    LemonSkeleton,
    LemonSwitch,
    LemonTable,
    LemonTag,
    Link,
    Spinner,
    Tooltip,
} from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { More } from 'lib/lemon-ui/LemonButton/More'
import cloudflareLogo from 'public/cloudflare-logo.svg'
import googleStorageLogo from 'public/google-cloud-storage-logo.png'
import hubspotLogo from 'public/hubspot-logo.svg'
import postgresLogo from 'public/postgres-logo.svg'
import s3Logo from 'public/s3-logo.png'
import snowflakeLogo from 'public/snowflake-logo.svg'
import stripeLogo from 'public/stripe-logo.svg'
import zendeskLogo from 'public/zendesk-logo.svg'
import { useEffect } from 'react'
import { urls } from 'scenes/urls'

import { DataTableNode, NodeKind } from '~/queries/schema'
import {
    DataWarehouseSyncInterval,
    ExternalDataSourceSchema,
    ExternalDataStripeSource,
    manualLinkSources,
    ProductKey,
} from '~/types'

import { SyncMethodForm } from '../external/forms/SyncMethodForm'
import { dataWarehouseSettingsLogic } from './dataWarehouseSettingsLogic'
import { dataWarehouseSourcesTableSyncMethodModalLogic } from './dataWarehouseSourcesTableSyncMethodModalLogic'

const StatusTagSetting = {
    Running: 'primary',
    Completed: 'success',
    Error: 'danger',
    Failed: 'danger',
}

export function DataWarehouseManagedSourcesTable(): JSX.Element {
    const { dataWarehouseSources, dataWarehouseSourcesLoading, sourceReloadingById } =
        useValues(dataWarehouseSettingsLogic)
    const { deleteSource, reloadSource, updateSource } = useActions(dataWarehouseSettingsLogic)

    const renderExpandable = (source: ExternalDataStripeSource): JSX.Element => {
        return (
            <div className="px-4 py-3">
                <div className="flex flex-col">
                    <div className="mt-2">
                        <SchemaTable schemas={source.schemas} />
                    </div>
                </div>
            </div>
        )
    }

    if (!dataWarehouseSourcesLoading && dataWarehouseSources?.results.length === 0) {
        return (
            <ProductIntroduction
                productName="Data Warehouse Source"
                productKey={ProductKey.DATA_WAREHOUSE}
                thingName="data source"
                description="Use data warehouse sources to import data from your external data into PostHog."
                isEmpty={dataWarehouseSources?.results.length == 0}
                docsURL="https://posthog.com/docs/data-warehouse"
                action={() => router.actions.push(urls.pipelineNodeDataWarehouseNew())}
            />
        )
    }

    return (
        <LemonTable
            dataSource={dataWarehouseSources?.results ?? []}
            loading={dataWarehouseSourcesLoading}
            disableTableWhileLoading={false}
            columns={[
                {
                    width: 0,
                    render: function RenderAppInfo(_, source) {
                        return <RenderDataWarehouseSourceIcon type={source.source_type} />
                    },
                },
                {
                    title: 'Source Type',
                    key: 'name',
                    render: function RenderName(_, source) {
                        return source.source_type
                    },
                },
                {
                    title: 'Table prefix',
                    key: 'prefix',
                    render: function RenderPrefix(_, source) {
                        return source.prefix
                    },
                },
                {
                    title: 'Sync Frequency',
                    key: 'frequency',
                    render: function RenderFrequency(_, source) {
                        return (
                            <LemonSelect
                                className="my-1"
                                value={source.sync_frequency || 'day'}
                                onChange={(value) =>
                                    updateSource({ ...source, sync_frequency: value as DataWarehouseSyncInterval })
                                }
                                options={[
                                    { value: 'day' as DataWarehouseSyncInterval, label: 'Daily' },
                                    { value: 'week' as DataWarehouseSyncInterval, label: 'Weekly' },
                                    { value: 'month' as DataWarehouseSyncInterval, label: 'Monthly' },
                                ]}
                            />
                        )
                    },
                },
                {
                    title: 'Last Successful Run',
                    key: 'last_run_at',
                    tooltip: 'Time of the last run that completed a data import',
                    render: (_, run) => {
                        return run.last_run_at ? (
                            <TZLabel time={run.last_run_at} formatDate="MMM DD, YYYY" formatTime="HH:mm" />
                        ) : (
                            'Never'
                        )
                    },
                },
                {
                    title: 'Total Rows Synced',
                    key: 'rows_synced',
                    tooltip: 'Total number of rows synced across all schemas in this source',
                    render: function RenderRowsSynced(_, source) {
                        return source.schemas.reduce((acc, schema) => acc + (schema.table?.row_count ?? 0), 0)
                    },
                },
                {
                    title: 'Status',
                    key: 'status',
                    render: function RenderStatus(_, source) {
                        return <LemonTag type={StatusTagSetting[source.status] || 'default'}>{source.status}</LemonTag>
                    },
                },
                {
                    key: 'actions',
                    width: 0,
                    render: function RenderActions(_, source) {
                        return (
                            <div className="flex flex-row justify-end">
                                {sourceReloadingById[source.id] ? (
                                    <div>
                                        <Spinner />
                                    </div>
                                ) : (
                                    <div>
                                        <More
                                            overlay={
                                                <>
                                                    <Tooltip title="Start the data import for this schema again">
                                                        <LemonButton
                                                            type="tertiary"
                                                            data-attr={`reload-data-warehouse-${source.source_type}`}
                                                            key={`reload-data-warehouse-${source.source_type}`}
                                                            onClick={() => {
                                                                reloadSource(source)
                                                            }}
                                                        >
                                                            Reload
                                                        </LemonButton>
                                                    </Tooltip>

                                                    <LemonButton
                                                        status="danger"
                                                        data-attr={`delete-data-warehouse-${source.source_type}`}
                                                        key={`delete-data-warehouse-${source.source_type}`}
                                                        onClick={() => {
                                                            LemonDialog.open({
                                                                title: 'Delete data source?',
                                                                description:
                                                                    'Are you sure you want to delete this data source? All related tables will be deleted.',

                                                                primaryButton: {
                                                                    children: 'Delete',
                                                                    status: 'danger',
                                                                    onClick: () => deleteSource(source),
                                                                },
                                                                secondaryButton: {
                                                                    children: 'Cancel',
                                                                },
                                                            })
                                                        }}
                                                    >
                                                        Delete
                                                    </LemonButton>
                                                </>
                                            }
                                        />
                                    </div>
                                )}
                            </div>
                        )
                    },
                },
            ]}
            expandable={{
                expandedRowRender: renderExpandable,
                rowExpandable: () => true,
                noIndent: true,
            }}
        />
    )
}

export function getDataWarehouseSourceUrl(service: string): string {
    if (manualLinkSources.includes(service)) {
        return 'https://posthog.com/docs/data-warehouse/setup#step-1-creating-a-bucket-in-s3'
    }

    return `https://posthog.com/docs/data-warehouse/setup#${service.toLowerCase()}`
}

export function RenderDataWarehouseSourceIcon({
    type,
    size = 'small',
}: {
    type: string
    size?: 'small' | 'medium'
}): JSX.Element {
    const sizePx = size === 'small' ? 30 : 60

    const icon = {
        Stripe: stripeLogo,
        Hubspot: hubspotLogo,
        Zendesk: zendeskLogo,
        Postgres: postgresLogo,
        Snowflake: snowflakeLogo,
        aws: s3Logo,
        'google-cloud': googleStorageLogo,
        'cloudflare-r2': cloudflareLogo,
    }[type]

    return (
        <div className="flex items-center gap-4">
            <Tooltip
                title={
                    <>
                        {type}
                        <br />
                        Click to view docs
                    </>
                }
            >
                <Link to={getDataWarehouseSourceUrl(type)}>
                    <img src={icon} alt={type} height={sizePx} width={sizePx} />
                </Link>
            </Tooltip>
        </div>
    )
}

interface SchemaTableProps {
    schemas: ExternalDataSourceSchema[]
}

const SchemaTable = ({ schemas }: SchemaTableProps): JSX.Element => {
    const { updateSchema, reloadSchema, resyncSchema } = useActions(dataWarehouseSettingsLogic)
    const { schemaReloadingById } = useValues(dataWarehouseSettingsLogic)

    return (
        <>
            <LemonTable
                dataSource={schemas}
                columns={[
                    {
                        title: 'Schema Name',
                        key: 'name',
                        render: function RenderName(_, schema) {
                            return <span>{schema.name}</span>
                        },
                    },
                    {
                        title: 'Sync method',
                        key: 'incremental',
                        render: function RenderIncremental(_, schema) {
                            const { openSyncMethodModal } = useActions(
                                dataWarehouseSourcesTableSyncMethodModalLogic({ schema })
                            )

                            if (!schema.sync_type) {
                                return (
                                    <>
                                        <LemonButton
                                            className="my-1"
                                            type="primary"
                                            onClick={() => openSyncMethodModal(schema)}
                                        >
                                            Set up
                                        </LemonButton>
                                        <SyncMethodModal schema={schema} />
                                    </>
                                )
                            }

                            return (
                                <>
                                    <LemonButton
                                        className="my-1"
                                        size="small"
                                        type="secondary"
                                        onClick={() => openSyncMethodModal(schema)}
                                    >
                                        {schema.sync_type == 'incremental' ? 'Incremental' : 'Full refresh'}
                                    </LemonButton>
                                    <SyncMethodModal schema={schema} />
                                </>
                            )
                        },
                    },
                    {
                        title: 'Enabled',
                        key: 'should_sync',
                        render: function RenderShouldSync(_, schema) {
                            return (
                                <LemonSwitch
                                    disabledReason={
                                        schema.sync_type === null ? 'You must set up the sync method first' : undefined
                                    }
                                    checked={schema.should_sync}
                                    onChange={(active) => {
                                        updateSchema({ ...schema, should_sync: active })
                                    }}
                                />
                            )
                        },
                    },
                    {
                        title: 'Synced Table',
                        key: 'table',
                        render: function RenderTable(_, schema) {
                            if (schema.table) {
                                const query: DataTableNode = {
                                    kind: NodeKind.DataTableNode,
                                    full: true,
                                    source: {
                                        kind: NodeKind.HogQLQuery,
                                        // TODO: Use `hogql` tag?
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
                                    <Link to={urls.dataWarehouse(JSON.stringify(query))}>
                                        <code>{schema.table.name}</code>
                                    </Link>
                                )
                            }
                            return <div>Not yet synced</div>
                        },
                    },
                    {
                        title: 'Last Synced At',
                        key: 'last_synced_at',
                        render: function Render(_, schema) {
                            return schema.last_synced_at ? (
                                <>
                                    <TZLabel
                                        time={schema.last_synced_at}
                                        formatDate="MMM DD, YYYY"
                                        formatTime="HH:mm"
                                    />
                                </>
                            ) : null
                        },
                    },
                    {
                        title: 'Rows Synced',
                        key: 'rows_synced',
                        render: function Render(_, schema) {
                            return schema.table?.row_count ?? ''
                        },
                    },
                    {
                        title: 'Status',
                        key: 'status',
                        render: function RenderStatus(_, schema) {
                            if (!schema.status) {
                                return null
                            }

                            return (
                                <LemonTag type={StatusTagSetting[schema.status] || 'default'}>{schema.status}</LemonTag>
                            )
                        },
                    },
                    {
                        key: 'actions',
                        width: 0,
                        render: function RenderActions(_, schema) {
                            if (schemaReloadingById[schema.id]) {
                                return (
                                    <div>
                                        <Spinner />
                                    </div>
                                )
                            }

                            return (
                                <div className="flex flex-row justify-end">
                                    <div>
                                        <More
                                            overlay={
                                                <>
                                                    <LemonButton
                                                        type="tertiary"
                                                        key={`reload-data-warehouse-schema-${schema.id}`}
                                                        onClick={() => {
                                                            reloadSchema(schema)
                                                        }}
                                                    >
                                                        Reload
                                                    </LemonButton>
                                                    {schema.incremental && (
                                                        <Tooltip title="Completely resync incrementally loaded data. Only recommended if there is an issue with data quality in previously imported data">
                                                            <LemonButton
                                                                type="tertiary"
                                                                key={`resync-data-warehouse-schema-${schema.id}`}
                                                                onClick={() => {
                                                                    resyncSchema(schema)
                                                                }}
                                                                status="danger"
                                                            >
                                                                Resync
                                                            </LemonButton>
                                                        </Tooltip>
                                                    )}
                                                </>
                                            }
                                        />
                                    </div>
                                </div>
                            )
                        },
                    },
                ]}
            />
        </>
    )
}

const SyncMethodModal = ({ schema }: { schema: ExternalDataSourceSchema }): JSX.Element => {
    const {
        syncMethodModalIsOpen,
        currentSyncMethodModalSchema,
        schemaIncrementalFields,
        schemaIncrementalFieldsLoading,
        saveButtonIsLoading,
    } = useValues(dataWarehouseSourcesTableSyncMethodModalLogic({ schema }))
    const { closeSyncMethodModal, loadSchemaIncrementalFields, resetSchemaIncrementalFields, updateSchema } =
        useActions(dataWarehouseSourcesTableSyncMethodModalLogic({ schema }))

    useEffect(() => {
        if (currentSyncMethodModalSchema?.id) {
            resetSchemaIncrementalFields()
            loadSchemaIncrementalFields(currentSyncMethodModalSchema.id)
        }
    }, [currentSyncMethodModalSchema?.id])

    const schemaLoading = schemaIncrementalFieldsLoading || !schemaIncrementalFields
    const showForm = !schemaLoading && schemaIncrementalFields

    if (!currentSyncMethodModalSchema) {
        return <></>
    }

    return (
        <LemonModal
            title={`Sync method for ${currentSyncMethodModalSchema.name}`}
            isOpen={syncMethodModalIsOpen}
            onClose={closeSyncMethodModal}
            footer={
                schemaLoading && (
                    <>
                        <LemonSkeleton.Button />
                        <LemonSkeleton.Button />
                    </>
                )
            }
        >
            {schemaLoading && (
                <div className="space-y-2">
                    <LemonSkeleton className="w-1/2 h-4" />
                    <LemonSkeleton.Row repeat={3} />
                </div>
            )}
            {showForm && (
                <SyncMethodForm
                    showRefreshMessageOnChange={currentSyncMethodModalSchema.sync_type !== null}
                    saveButtonIsLoading={saveButtonIsLoading}
                    schema={{
                        table: currentSyncMethodModalSchema.name,
                        should_sync: currentSyncMethodModalSchema.should_sync,
                        sync_type: currentSyncMethodModalSchema.sync_type,
                        incremental_field: currentSyncMethodModalSchema.incremental_field ?? null,
                        incremental_field_type: currentSyncMethodModalSchema.incremental_field_type ?? null,
                        incremental_available: !!schemaIncrementalFields.length,
                        incremental_fields: schemaIncrementalFields,
                    }}
                    onClose={() => {
                        resetSchemaIncrementalFields()
                        closeSyncMethodModal()
                    }}
                    onSave={(syncType, incrementalField, incrementalFieldType) => {
                        if (syncType === 'full_refresh') {
                            updateSchema({
                                ...currentSyncMethodModalSchema,
                                should_sync: true,
                                sync_type: syncType,
                                incremental_field: null,
                                incremental_field_type: null,
                            })
                        } else {
                            updateSchema({
                                ...currentSyncMethodModalSchema,
                                should_sync: true,
                                sync_type: syncType,
                                incremental_field: incrementalField,
                                incremental_field_type: incrementalFieldType,
                            })
                        }
                    }}
                />
            )}
        </LemonModal>
    )
}
