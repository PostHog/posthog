import { IconInfo } from '@posthog/icons'
import {
    LemonButton,
    LemonInput,
    LemonModal,
    LemonSelect,
    LemonSkeleton,
    LemonSwitch,
    LemonTable,
    LemonTag,
    LemonTagType,
    Link,
    Spinner,
    Tooltip,
} from '@posthog/lemon-ui'
import { BindLogic, useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { ProductIntentContext } from 'lib/utils/product-intents'
import { useEffect, useState } from 'react'
import { defaultQuery, syncAnchorIntervalToHumanReadable, SyncTypeLabelMap } from 'scenes/data-warehouse/utils'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import {
    DataWarehouseSyncInterval,
    ExternalDataJobStatus,
    ExternalDataSchemaStatus,
    ExternalDataSourceSchema,
    ProductKey,
} from '~/types'

import { SyncMethodForm } from '../../external/forms/SyncMethodForm'
import { dataWarehouseSettingsLogic } from '../dataWarehouseSettingsLogic'
import { dataWarehouseSourcesTableSyncMethodModalLogic } from '../dataWarehouseSourcesTableSyncMethodModalLogic'
import { dataWarehouseSourceSettingsLogic } from './dataWarehouseSourceSettingsLogic'
import { ExternalDataSourceType } from '~/queries/schema/schema-general'

interface SchemasProps {
    id: string
}

const REVENUE_ENABLED_SOURCES: ExternalDataSourceType[] = ['Stripe']
export const Schemas = ({ id }: SchemasProps): JSX.Element => {
    const { source, sourceLoading } = useValues(dataWarehouseSourceSettingsLogic({ id }))
    const { addProductIntentForCrossSell } = useActions(teamLogic)

    return (
        <BindLogic logic={dataWarehouseSourceSettingsLogic} props={{ id }}>
            <SchemaTable schemas={source?.schemas ?? []} isLoading={sourceLoading} />
            {source?.source_type && REVENUE_ENABLED_SOURCES.includes(source.source_type) && (
                <div className="flex justify-end">
                    <LemonButton
                        type="primary"
                        className="mt-2"
                        tooltip="This source is feeding data into our Revenue analytics product - currently in beta."
                        onClick={() => {
                            addProductIntentForCrossSell({
                                from: ProductKey.PRODUCT_ANALYTICS,
                                to: ProductKey.DATA_WAREHOUSE,
                                intent_context: ProductIntentContext.DATA_WAREHOUSE_SOURCES_TABLE,
                            })
                            router.actions.push(urls.revenueAnalytics())
                        }}
                    >
                        See data in Revenue analytics
                        <LemonTag className="ml-2" type="warning" size="small">
                            BETA
                        </LemonTag>
                    </LemonButton>
                </div>
            )}
        </BindLogic>
    )
}

interface SchemaTableProps {
    schemas: ExternalDataSourceSchema[]
    isLoading: boolean
}

const StatusTagSetting: Record<ExternalDataSchemaStatus | ExternalDataJobStatus, LemonTagType> = {
    Running: 'primary',
    Completed: 'success',
    Failed: 'danger',
    'Billing limits': 'danger',
    'Billing limit too low': 'danger',
    Cancelled: 'warning',
    Paused: 'warning',
}

export const SchemaTable = ({ schemas, isLoading }: SchemaTableProps): JSX.Element => {
    const { currentTeam } = useValues(teamLogic)
    const { updateSchema, reloadSchema, resyncSchema, deleteTable, setIsProjectTime } = useActions(
        dataWarehouseSourceSettingsLogic
    )
    const { isProjectTime, source } = useValues(dataWarehouseSourceSettingsLogic)
    const { schemaReloadingById } = useValues(dataWarehouseSettingsLogic)
    const [initialLoad, setInitialLoad] = useState(true)

    useEffect(() => {
        if (initialLoad && !isLoading) {
            setInitialLoad(false)
        }
    }, [isLoading])

    return (
        <>
            <LemonTable
                dataSource={schemas}
                loading={initialLoad}
                disableTableWhileLoading={false}
                columns={[
                    {
                        title: 'Schema Name',
                        key: 'name',
                        render: function RenderName(_, schema) {
                            return <span>{schema.name}</span>
                        },
                    },
                    {
                        title: (
                            <div className="flex items-center gap-2">
                                <span>Anchor Time</span>
                                <div className="flex items-center gap-1">
                                    <span>UTC</span>
                                    {currentTeam?.timezone !== 'UTC' && currentTeam?.timezone !== 'GMT' && (
                                        <>
                                            <LemonSwitch
                                                size="xsmall"
                                                checked={isProjectTime}
                                                onChange={setIsProjectTime}
                                            />
                                            <span>{currentTeam?.timezone || 'UTC'}</span>
                                        </>
                                    )}
                                </div>
                            </div>
                        ),
                        tooltip: `The sync frequency will be offset from the anchor time. This will not apply to sync intervals one hour or less.`,
                        key: 'sync_time_of_day',
                        render: function RenderSyncTimeOfDayLocal(_, schema) {
                            const utcTime = schema.sync_time_of_day || '00:00:00'
                            const localTime = isProjectTime
                                ? dayjs
                                      .utc(`${dayjs().format('YYYY-MM-DD')}T${utcTime}`)
                                      .local()
                                      .tz(currentTeam?.timezone || 'UTC')
                                      .format('HH:mm:00')
                                : utcTime

                            return (
                                <LemonInput
                                    type="time"
                                    size="xsmall"
                                    disabled={
                                        !schema.should_sync ||
                                        schema.sync_frequency === '5min' ||
                                        schema.sync_frequency === '30min' ||
                                        schema.sync_frequency === '1hour'
                                    }
                                    value={localTime.substring(0, 5)}
                                    onChange={(value) => {
                                        const newValue = `${value}:00`
                                        const utcValue = isProjectTime
                                            ? dayjs(`${dayjs().format('YYYY-MM-DD')}T${newValue}`)
                                                  .tz(currentTeam?.timezone || 'UTC')
                                                  .utc()
                                                  .format('HH:mm:00')
                                            : newValue
                                        updateSchema({ ...schema, sync_time_of_day: utcValue })
                                    }}
                                    suffix={
                                        <Tooltip
                                            title={syncAnchorIntervalToHumanReadable(utcTime, schema.sync_frequency)}
                                        >
                                            {schema.should_sync && <IconInfo className="text-muted-alt" />}
                                        </Tooltip>
                                    }
                                />
                            )
                        },
                    },
                    {
                        title: 'Sync Frequency',
                        key: 'frequency',
                        className: 'px-1',
                        render: function RenderFrequency(_, schema) {
                            return (
                                <LemonSelect
                                    className="my-1"
                                    size="xsmall"
                                    disabled={!schema.should_sync}
                                    value={schema.sync_frequency || '6hour'}
                                    onChange={(value) =>
                                        updateSchema({ ...schema, sync_frequency: value as DataWarehouseSyncInterval })
                                    }
                                    options={[
                                        { value: '5min' as DataWarehouseSyncInterval, label: '5 mins' },
                                        { value: '30min' as DataWarehouseSyncInterval, label: '30 mins' },
                                        { value: '1hour' as DataWarehouseSyncInterval, label: '1 hour' },
                                        { value: '6hour' as DataWarehouseSyncInterval, label: '6 hours' },
                                        { value: '12hour' as DataWarehouseSyncInterval, label: '12 hours' },
                                        { value: '24hour' as DataWarehouseSyncInterval, label: 'Daily' },
                                        { value: '7day' as DataWarehouseSyncInterval, label: 'Weekly' },
                                        { value: '30day' as DataWarehouseSyncInterval, label: 'Monthly' },
                                    ]}
                                />
                            )
                        },
                    },
                    {
                        title: 'Sync method',
                        key: 'incremental',
                        className: 'px-1',
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
                                            size="xsmall"
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
                                        size="xsmall"
                                        type="secondary"
                                        onClick={() => openSyncMethodModal(schema)}
                                    >
                                        {SyncTypeLabelMap[schema.sync_type]}
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
                                const query = defaultQuery(schema.table.name, schema.table.columns)
                                return (
                                    <Link to={urls.sqlEditor(query.source.query)}>
                                        <code>{schema.table.name}</code>
                                    </Link>
                                )
                            }

                            // Synced but no rows
                            if (schema.status === 'Completed') {
                                return <div>No rows to query</div>
                            }

                            if (schema.status === 'Running') {
                                return <div>Syncing...</div>
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
                            if (schema.table) {
                                return schema.table.row_count.toLocaleString()
                            }

                            // Synced but no rows
                            if (schema.status === 'Completed') {
                                return 0
                            }

                            return ''
                        },
                    },
                    {
                        title: 'Status',
                        key: 'status',
                        render: (_, schema) => {
                            if (!schema.status) {
                                return null
                            }
                            const tagContent = (
                                <LemonTag type={StatusTagSetting[schema.status] || 'default'}>
                                    {schema.status}
                                    {schema.latest_error && schema.status === 'Failed' && (
                                        <span className="ml-0.5 inline-flex items-center justify-center w-3 h-3 bg-danger/90 text-white rounded-full text-[10px] font-medium tracking-tight shadow-md backdrop-blur-sm border border-danger/20">
                                            ?
                                        </span>
                                    )}
                                </LemonTag>
                            )
                            return schema.latest_error && schema.status === 'Failed' ? (
                                <Tooltip title={schema.latest_error}>{tagContent}</Tooltip>
                            ) : (
                                tagContent
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
                                                    <Tooltip
                                                        title={
                                                            schema.incremental
                                                                ? 'Sync incremental data since the last run.'
                                                                : 'Sync all data.'
                                                        }
                                                    >
                                                        <LemonButton
                                                            type="tertiary"
                                                            size="xsmall"
                                                            fullWidth
                                                            key={`reload-data-warehouse-schema-${schema.id}`}
                                                            id="data-warehouse-schema-reload"
                                                            onClick={() => {
                                                                reloadSchema(schema)
                                                            }}
                                                        >
                                                            Sync now
                                                        </LemonButton>
                                                    </Tooltip>
                                                    {schema.incremental && (
                                                        <Tooltip title="Completely resync incrementally loaded data. Only recommended if there is an issue with data quality in previously imported data.">
                                                            <LemonButton
                                                                type="tertiary"
                                                                size="xsmall"
                                                                fullWidth
                                                                key={`resync-data-warehouse-schema-${schema.id}`}
                                                                id="data-warehouse-schema-resync"
                                                                onClick={() => {
                                                                    resyncSchema(schema)
                                                                }}
                                                                status="danger"
                                                            >
                                                                Delete table and resync
                                                            </LemonButton>
                                                        </Tooltip>
                                                    )}
                                                    {schema.table && (
                                                        <Tooltip
                                                            title={`Delete this table from PostHog. ${
                                                                source?.source_type
                                                                    ? `This will not delete the data in ${source.source_type}`
                                                                    : ''
                                                            }`}
                                                        >
                                                            <LemonButton
                                                                status="danger"
                                                                id="data-warehouse-schema-delete"
                                                                type="tertiary"
                                                                fullWidth
                                                                size="xsmall"
                                                                onClick={() => {
                                                                    if (
                                                                        window.confirm(
                                                                            `Are you sure you want to delete the table ${schema?.table?.name} from PostHog?`
                                                                        )
                                                                    ) {
                                                                        deleteTable(schema)
                                                                    }
                                                                }}
                                                            >
                                                                Delete table from PostHog
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
    const logic = dataWarehouseSourcesTableSyncMethodModalLogic({ schema })

    const {
        syncMethodModalIsOpen,
        currentSyncMethodModalSchema,
        schemaIncrementalFields,
        schemaIncrementalFieldsLoading,
        saveButtonIsLoading,
    } = useValues(logic)
    const { closeSyncMethodModal, loadSchemaIncrementalFields, resetSchemaIncrementalFields, updateSchema } =
        useActions(logic)

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
            title={
                <>
                    Sync method for <span className="font-mono">{currentSyncMethodModalSchema.name}</span>
                </>
            }
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
                <div className="deprecated-space-y-2">
                    <LemonSkeleton className="w-1/2 h-4" />
                    <LemonSkeleton.Row repeat={3} />
                </div>
            )}
            {showForm && (
                <SyncMethodForm
                    saveButtonIsLoading={saveButtonIsLoading}
                    schema={{
                        table: currentSyncMethodModalSchema.name,
                        should_sync: currentSyncMethodModalSchema.should_sync,
                        sync_type: currentSyncMethodModalSchema.sync_type,
                        sync_time_of_day: currentSyncMethodModalSchema.sync_time_of_day ?? '00:00:00',
                        incremental_field: currentSyncMethodModalSchema.incremental_field ?? null,
                        incremental_field_type: currentSyncMethodModalSchema.incremental_field_type ?? null,
                        incremental_available: schemaIncrementalFields.incremental_available,
                        append_available: schemaIncrementalFields.append_available,
                        incremental_fields: schemaIncrementalFields.incremental_fields,
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
                                sync_time_of_day: currentSyncMethodModalSchema.sync_time_of_day ?? '00:00:00',
                            })
                        } else {
                            updateSchema({
                                ...currentSyncMethodModalSchema,
                                should_sync: true,
                                sync_type: syncType,
                                incremental_field: incrementalField,
                                incremental_field_type: incrementalFieldType,
                                sync_time_of_day: currentSyncMethodModalSchema.sync_time_of_day ?? '00:00:00',
                            })
                        }
                    }}
                />
            )}
        </LemonModal>
    )
}
