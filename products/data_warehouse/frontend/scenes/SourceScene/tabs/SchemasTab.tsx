import { BindLogic, useActions, useValues } from 'kea'
import { router } from 'kea-router'
import React, { useCallback, useEffect, useState } from 'react'

import { IconInfo } from '@posthog/icons'
import {
    LemonButton,
    LemonCheckbox,
    LemonCollapse,
    LemonDialog,
    LemonInput,
    LemonModal,
    LemonSelect,
    LemonSelectOption,
    LemonSkeleton,
    LemonSwitch,
    LemonTable,
    LemonTag,
    LemonTagType,
    Link,
    Spinner,
    Tooltip,
} from '@posthog/lemon-ui'

import { AccessControlAction, AccessControlActionChildrenProps } from 'lib/components/AccessControlAction'
import { TZLabel } from 'lib/components/TZLabel'
import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { groupBy, pluralize } from 'lib/utils'
import { newInternalTab } from 'lib/utils/newInternalTab'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { ExternalDataSourceType, ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'
import {
    AccessControlLevel,
    AccessControlResourceType,
    DataWarehouseSyncInterval,
    ExternalDataJobStatus,
    ExternalDataSchemaStatus,
    ExternalDataSource,
    ExternalDataSourceSchema,
} from '~/types'

import {
    SyncTypeLabelMap,
    buildTableQueryUrl,
    defaultQuery,
    syncAnchorIntervalToHumanReadable,
} from 'products/data_warehouse/frontend/utils'

import { SyncMethodForm } from '../../../shared/components/forms/SyncMethodForm'
import { sourceManagementLogic } from '../../../shared/logics/sourceManagementLogic'
import { syncMethodModalLogic } from '../syncMethodModalLogic'
import { sourceSettingsLogic } from './sourceSettingsLogic'

/**
 * Wrapper component for AccessControlAction with common external data source editor props.
 * Reduces repetition when checking editor access for source operations.
 */
const SourceEditorAction = ({
    source,
    children,
}: {
    source: ExternalDataSource | null
    children:
        | React.ComponentType<AccessControlActionChildrenProps>
        | React.ReactElement<AccessControlActionChildrenProps>
}): JSX.Element => (
    <AccessControlAction
        resourceType={AccessControlResourceType.ExternalDataSource}
        minAccessLevel={AccessControlLevel.Editor}
        userAccessLevel={source?.user_access_level}
    >
        {children}
    </AccessControlAction>
)

export interface SchemasTabProps {
    id: string
}

export function splitDirectQuerySchemaName(
    name: string,
    fallbackSchema?: string | null
): { schemaName: string; tableName: string } {
    const firstDotIndex = name.indexOf('.')

    if (firstDotIndex === -1) {
        const normalizedFallbackSchema = fallbackSchema?.trim()
        return {
            schemaName: normalizedFallbackSchema || 'Unqualified',
            tableName: name,
        }
    }

    return {
        schemaName: name.slice(0, firstDotIndex),
        tableName: name.slice(firstDotIndex + 1),
    }
}

export function groupDirectQuerySourceSchemasBySchema(
    schemas: ExternalDataSourceSchema[],
    fallbackSchema?: string | null
): { schemaName: string; schemas: ExternalDataSourceSchema[] }[] {
    return Object.entries(
        groupBy(
            schemas,
            (schema) => splitDirectQuerySchemaName(schema.table?.name ?? schema.name, fallbackSchema).schemaName
        )
    )
        .sort(([schemaA], [schemaB]) => schemaA.localeCompare(schemaB))
        .map(([schemaName, groupedSchemas]) => ({ schemaName, schemas: groupedSchemas }))
}

function getSchemaSelectionState(schemas: ExternalDataSourceSchema[]): boolean | 'indeterminate' {
    const enabledCount = schemas.filter((schema) => schema.should_sync).length

    if (enabledCount === 0) {
        return false
    }

    if (enabledCount === schemas.length) {
        return true
    }

    return 'indeterminate'
}

const REVENUE_ENABLED_SOURCES: ExternalDataSourceType[] = ['Stripe']
export const SchemasTab = ({ id }: SchemasTabProps): JSX.Element => {
    const logicProps = { id, availableSources: {} }
    const logic = sourceSettingsLogic(logicProps)
    const {
        source,
        sourceLoading,
        filteredSchemas,
        showEnabledSchemasOnly,
        schemaNameFilter,
        isProjectTime,
        syncingNow,
        refreshingSchemas,
    } = useValues(logic)
    const {
        setShowEnabledSchemasOnly,
        setSchemaNameFilter,
        setIsProjectTime,
        syncNow,
        refreshSchemas,
        updateSchema,
        reloadSchema,
        resyncSchema,
        cancelSchema,
        deleteTable,
    } = useActions(logic)
    const { addProductIntentForCrossSell } = useActions(teamLogic)

    const { featureFlags } = useValues(featureFlagLogic)
    const isDirectQuerySource =
        !!featureFlags[FEATURE_FLAGS.DWH_POSTGRES_DIRECT_QUERY] && source?.access_method === 'direct'
    const directQueryDefaultSchema = typeof source?.job_inputs?.schema === 'string' ? source.job_inputs.schema : null
    const groupedDirectQuerySchemas = groupDirectQuerySourceSchemasBySchema(filteredSchemas, directQueryDefaultSchema)

    return (
        <BindLogic logic={sourceSettingsLogic} props={logicProps}>
            <div className="flex items-center justify-between gap-2 mb-2">
                <div className="flex items-center gap-3">
                    <LemonSwitch
                        checked={showEnabledSchemasOnly}
                        onChange={setShowEnabledSchemasOnly}
                        label={isDirectQuerySource ? 'Show queryable only' : 'Show enabled only'}
                    />
                    <LemonInput
                        type="search"
                        placeholder="Filter schemas"
                        size="small"
                        value={schemaNameFilter}
                        onChange={setSchemaNameFilter}
                    />
                    <span className="text-muted text-sm">
                        {pluralize(
                            isDirectQuerySource ? groupedDirectQuerySchemas.length : filteredSchemas.length,
                            'schema',
                            'schemas'
                        )}
                    </span>
                </div>
                <div className="flex items-center gap-2">
                    {!isDirectQuerySource && (
                        <SourceEditorAction source={source}>
                            <LemonButton
                                type="secondary"
                                loading={syncingNow}
                                onClick={() => {
                                    LemonDialog.open({
                                        title: 'Sync all enabled schemas?',
                                        content: (
                                            <div className="text-sm text-secondary">
                                                This will trigger a sync for all schemas you have enabled. New sync jobs
                                                will appear in the Syncs tab.
                                            </div>
                                        ),
                                        primaryButton: {
                                            children: 'Sync now',
                                            type: 'primary',
                                            onClick: () => syncNow(),
                                        },
                                        secondaryButton: {
                                            children: 'Cancel',
                                            type: 'tertiary',
                                        },
                                    })
                                }}
                                disabledReason={
                                    sourceLoading
                                        ? 'Source is loading'
                                        : refreshingSchemas
                                          ? 'Schema refresh in progress'
                                          : undefined
                                }
                            >
                                Sync now
                            </LemonButton>
                        </SourceEditorAction>
                    )}
                    <SourceEditorAction source={source}>
                        <LemonButton
                            type="secondary"
                            loading={refreshingSchemas}
                            onClick={() => refreshSchemas()}
                            disabledReason={
                                sourceLoading ? 'Source is loading' : syncingNow ? 'Sync in progress' : undefined
                            }
                        >
                            Pull new schemas
                        </LemonButton>
                    </SourceEditorAction>
                </div>
            </div>
            <SchemaTable
                schemas={filteredSchemas}
                isLoading={sourceLoading}
                isDirectQuerySource={isDirectQuerySource}
                source={source}
                isProjectTime={isProjectTime}
                updateSchema={updateSchema}
                reloadSchema={reloadSchema}
                resyncSchema={resyncSchema}
                cancelSchema={cancelSchema}
                deleteTable={deleteTable}
                setIsProjectTime={setIsProjectTime}
            />
            {source?.source_type &&
                REVENUE_ENABLED_SOURCES.includes(source.source_type) &&
                featureFlags[FEATURE_FLAGS.REVENUE_ANALYTICS] && (
                    <div className="flex justify-end">
                        <LemonButton
                            type="primary"
                            className="mt-2"
                            tooltip="This source is feeding data into our Revenue analytics product - currently in beta."
                            onClick={() => {
                                addProductIntentForCrossSell({
                                    from: ProductKey.DATA_WAREHOUSE,
                                    to: ProductKey.REVENUE_ANALYTICS,
                                    intent_context: ProductIntentContext.DATA_WAREHOUSE_STRIPE_SOURCE_CREATED,
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
    isDirectQuerySource: boolean
    source: ExternalDataSource | null
    isProjectTime: boolean
    updateSchema: (schema: ExternalDataSourceSchema) => void
    reloadSchema: (schema: ExternalDataSourceSchema) => void
    resyncSchema: (schema: ExternalDataSourceSchema) => void
    cancelSchema: (schema: ExternalDataSourceSchema) => void
    deleteTable: (schema: ExternalDataSourceSchema) => void
    setIsProjectTime: (isProjectTime: boolean) => void
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

interface DirectQuerySchemaGroupsProps {
    groupedSchemas: { schemaName: string; schemas: ExternalDataSourceSchema[] }[]
    expandedSchemaKeys: string[]
    initialLoad: boolean
    source: ExternalDataSource | null
    getPreviewUrl: (tableName: string) => string
    setExpandedSchemaKeys: (keys: string[]) => void
    setDirectQuerySchemaEnabled: (schema: ExternalDataSourceSchema, shouldSync: boolean) => void
    toggleDirectQuerySchemaGroup: (schemaName: string, shouldSync: boolean) => void
}

function DirectQuerySchemaGroups({
    groupedSchemas,
    expandedSchemaKeys,
    initialLoad,
    source,
    getPreviewUrl,
    setExpandedSchemaKeys,
    setDirectQuerySchemaEnabled,
    toggleDirectQuerySchemaGroup,
}: DirectQuerySchemaGroupsProps): JSX.Element {
    if (initialLoad) {
        return <LemonSkeleton className="h-48" />
    }

    if (groupedSchemas.length === 0) {
        return <div className="border rounded px-4 py-8 text-center text-muted-alt">No schemas found</div>
    }

    return (
        <div className="border rounded bg-bg-light">
            <LemonCollapse
                multiple
                embedded
                activeKeys={expandedSchemaKeys}
                onChange={setExpandedSchemaKeys}
                panels={groupedSchemas.map(({ schemaName, schemas }) => {
                    const selectedTablesCount = schemas.filter((schema) => schema.should_sync).length

                    return {
                        key: schemaName,
                        header: (
                            <div className="flex items-center justify-between gap-3 w-full">
                                <div className="flex items-center gap-2 min-w-0">
                                    <LemonCheckbox
                                        checked={getSchemaSelectionState(schemas)}
                                        stopPropagation
                                        onChange={(checked) => toggleDirectQuerySchemaGroup(schemaName, checked)}
                                    />
                                    <span className="font-semibold truncate">{schemaName}</span>
                                </div>
                                <span className="text-xs text-muted-alt whitespace-nowrap">
                                    {selectedTablesCount} of {schemas.length} tables queryable
                                </span>
                            </div>
                        ),
                        content: (
                            <div className="bg-bg-light">
                                <div>
                                    {schemas.map((schema) => {
                                        const qualifiedName = schema.table?.name ?? schema.name
                                        const { tableName } = splitDirectQuerySchemaName(
                                            qualifiedName,
                                            typeof source?.job_inputs?.schema === 'string'
                                                ? source.job_inputs.schema
                                                : null
                                        )

                                        return (
                                            <div
                                                key={schema.id}
                                                className="grid grid-cols-[auto_minmax(0,1fr)] gap-2 px-6 py-1 items-center"
                                            >
                                                <SourceEditorAction source={source}>
                                                    <LemonCheckbox
                                                        checked={schema.should_sync}
                                                        onChange={(active) =>
                                                            setDirectQuerySchemaEnabled(schema, active)
                                                        }
                                                    />
                                                </SourceEditorAction>
                                                <div className="flex items-center gap-1 min-w-0">
                                                    {schema.should_sync ? (
                                                        <Link
                                                            to={getPreviewUrl(qualifiedName)}
                                                            className="truncate"
                                                            onClick={(event) => {
                                                                event.preventDefault()
                                                                newInternalTab(getPreviewUrl(qualifiedName))
                                                            }}
                                                        >
                                                            {tableName}
                                                        </Link>
                                                    ) : (
                                                        <span className="truncate">{tableName}</span>
                                                    )}
                                                    {schema.description && (
                                                        <Tooltip title={schema.description}>
                                                            <IconInfo className="text-muted-alt text-base shrink-0" />
                                                        </Tooltip>
                                                    )}
                                                </div>
                                            </div>
                                        )
                                    })}
                                </div>
                            </div>
                        ),
                    }
                })}
            />
        </div>
    )
}

export const SchemaTable = ({
    schemas,
    isLoading,
    isDirectQuerySource,
    source,
    isProjectTime,
    updateSchema,
    reloadSchema,
    resyncSchema,
    cancelSchema,
    deleteTable,
    setIsProjectTime,
}: SchemaTableProps): JSX.Element => {
    const { currentTeam } = useValues(teamLogic)
    const { schemaReloadingById } = useValues(sourceManagementLogic)
    const [initialLoad, setInitialLoad] = useState(true)
    const directQueryDefaultSchema = typeof source?.job_inputs?.schema === 'string' ? source.job_inputs.schema : null
    const groupedDirectQuerySchemas = groupDirectQuerySourceSchemasBySchema(schemas, directQueryDefaultSchema)
    const groupedSchemaKeys = groupedDirectQuerySchemas.map((group) => group.schemaName)
    const groupedSchemaKeysFingerprint = groupedSchemaKeys.join('|')
    const [expandedSchemaKeys, setExpandedSchemaKeys] = useState<string[]>([])

    useEffect(() => {
        if (initialLoad && !isLoading) {
            setInitialLoad(false)
        }
    }, [isLoading, initialLoad])

    useEffect(() => {
        if (!isDirectQuerySource) {
            return
        }

        setExpandedSchemaKeys((currentKeys) => {
            const nextKeys = currentKeys.filter((key) => groupedSchemaKeys.includes(key))

            if (
                nextKeys.length > 0 &&
                nextKeys.length === currentKeys.length &&
                nextKeys.every((key, index) => key === currentKeys[index])
            ) {
                return currentKeys
            }

            if (nextKeys.length > 0) {
                return nextKeys
            }

            return groupedSchemaKeys
        })
    }, [groupedSchemaKeysFingerprint, isDirectQuerySource])
    const directConnectionId = isDirectQuerySource ? source?.id : undefined
    const getPreviewUrl = useCallback(
        (tableName: string): string => buildTableQueryUrl(tableName, directConnectionId),
        [directConnectionId]
    )
    const setDirectQuerySchemaEnabled = useCallback(
        (schema: ExternalDataSourceSchema, shouldSync: boolean) => {
            updateSchema({ ...schema, should_sync: shouldSync })
        },
        [updateSchema]
    )
    const toggleDirectQuerySchemaGroup = useCallback(
        (schemaName: string, shouldSync: boolean) => {
            const schemaGroup = groupedDirectQuerySchemas.find((group) => group.schemaName === schemaName)

            for (const schema of schemaGroup?.schemas ?? []) {
                setDirectQuerySchemaEnabled(schema, shouldSync)
            }

            setExpandedSchemaKeys((currentKeys) =>
                shouldSync
                    ? Array.from(new Set([...currentKeys, schemaName]))
                    : currentKeys.filter((key) => key !== schemaName)
            )
        },
        [groupedDirectQuerySchemas, setDirectQuerySchemaEnabled]
    )

    if (isDirectQuerySource) {
        return (
            <DirectQuerySchemaGroups
                groupedSchemas={groupedDirectQuerySchemas}
                expandedSchemaKeys={expandedSchemaKeys}
                initialLoad={initialLoad}
                source={source}
                getPreviewUrl={getPreviewUrl}
                setExpandedSchemaKeys={setExpandedSchemaKeys}
                setDirectQuerySchemaEnabled={setDirectQuerySchemaEnabled}
                toggleDirectQuerySchemaGroup={toggleDirectQuerySchemaGroup}
            />
        )
    }

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
                            const nameContent =
                                isDirectQuerySource && schema.table ? (
                                    <Link to={getPreviewUrl(schema.table.name)}>{schema.label ?? schema.name}</Link>
                                ) : (
                                    <span>{schema.label ?? schema.name}</span>
                                )
                            return (
                                <div className="flex items-center gap-1">
                                    {nameContent}
                                    {schema.description && (
                                        <Tooltip title={schema.description}>
                                            <IconInfo className="text-muted-alt text-base" />
                                        </Tooltip>
                                    )}
                                </div>
                            )
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
                        isHidden: isDirectQuerySource,
                        render: function RenderSyncTimeOfDayLocal(_, schema) {
                            return (
                                <SourceEditorAction source={source}>
                                    {({ disabledReason }) => (
                                        <AnchorTime
                                            schema={schema}
                                            disabledReason={disabledReason}
                                            isProjectTime={isProjectTime}
                                            updateSchema={updateSchema}
                                        />
                                    )}
                                </SourceEditorAction>
                            )
                        },
                    },
                    {
                        title: 'Sync Frequency',
                        key: 'frequency',
                        className: 'px-1',
                        isHidden: isDirectQuerySource,
                        render: function RenderFrequency(_, schema) {
                            const isCdc = schema.sync_type === 'cdc'
                            const cdcOnlyOptions: LemonSelectOption<DataWarehouseSyncInterval>[] = [
                                { value: '1min', label: '1 min' },
                            ]
                            const standardOptions: LemonSelectOption<DataWarehouseSyncInterval>[] = [
                                { value: '5min', label: '5 mins' },
                                { value: '15min', label: '15 mins' },
                                { value: '30min', label: '30 mins' },
                                { value: '1hour', label: '1 hour' },
                                { value: '6hour', label: '6 hours' },
                                { value: '12hour', label: '12 hours' },
                                { value: '24hour', label: 'Daily' },
                                { value: '7day', label: 'Weekly' },
                                { value: '30day', label: 'Monthly' },
                            ]
                            return (
                                <SourceEditorAction source={source}>
                                    <LemonSelect
                                        className="my-1"
                                        size="xsmall"
                                        disabled={!schema.should_sync}
                                        value={schema.sync_frequency || (isCdc ? '5min' : '6hour')}
                                        onChange={(value) =>
                                            updateSchema({
                                                ...schema,
                                                sync_frequency: value as DataWarehouseSyncInterval,
                                            })
                                        }
                                        options={isCdc ? [...cdcOnlyOptions, ...standardOptions] : standardOptions}
                                    />
                                </SourceEditorAction>
                            )
                        },
                    },
                    {
                        title: 'Sync method',
                        key: 'incremental',
                        className: 'px-1',
                        isHidden: isDirectQuerySource,
                        render: function RenderIncremental(_, schema) {
                            const { openSyncMethodModal } = useActions(syncMethodModalLogic({ schema }))

                            if (!schema.sync_type) {
                                return (
                                    <>
                                        <SourceEditorAction source={source}>
                                            <LemonButton
                                                className="my-1"
                                                type="primary"
                                                size="xsmall"
                                                onClick={() => openSyncMethodModal(schema)}
                                            >
                                                Set up
                                            </LemonButton>
                                        </SourceEditorAction>
                                        <SyncMethodModal schema={schema} />
                                    </>
                                )
                            }

                            return (
                                <>
                                    <SourceEditorAction source={source}>
                                        <LemonButton
                                            className="my-1"
                                            size="xsmall"
                                            type="secondary"
                                            onClick={() => openSyncMethodModal(schema)}
                                        >
                                            {SyncTypeLabelMap[schema.sync_type]}
                                        </LemonButton>
                                    </SourceEditorAction>
                                    <SyncMethodModal schema={schema} />
                                </>
                            )
                        },
                    },
                    {
                        title: isDirectQuerySource ? 'Queryable' : 'Enabled',
                        key: 'should_sync',
                        sorter: (a, b) => Number(a.should_sync) - Number(b.should_sync),
                        render: function RenderShouldSync(_, schema) {
                            return (
                                <SourceEditorAction source={source}>
                                    <LemonSwitch
                                        disabledReason={
                                            !isDirectQuerySource && schema.sync_type === null
                                                ? 'You must set up the sync method first'
                                                : undefined
                                        }
                                        checked={schema.should_sync}
                                        onChange={(active) => {
                                            if (!active && schema.sync_type === 'cdc') {
                                                LemonDialog.open({
                                                    title: 'Disable CDC table?',
                                                    content: (
                                                        <div className="text-sm text-secondary space-y-2">
                                                            <p>
                                                                Disabling{' '}
                                                                <strong>{schema.table?.name ?? schema.name}</strong>{' '}
                                                                will remove it from the replication publication. Changes
                                                                made while disabled will be permanently lost.
                                                            </p>
                                                            <p>
                                                                Re-enabling this table will require a{' '}
                                                                <strong>full resync</strong> to ensure data consistency.
                                                            </p>
                                                        </div>
                                                    ),
                                                    primaryButton: {
                                                        children: 'Disable',
                                                        status: 'danger',
                                                        onClick: () => updateSchema({ ...schema, should_sync: false }),
                                                    },
                                                    secondaryButton: {
                                                        children: 'Cancel',
                                                        type: 'tertiary',
                                                    },
                                                })
                                            } else if (!active && schema.sync_type === 'webhook') {
                                                LemonDialog.open({
                                                    title: 'Disable webhook sync?',
                                                    description:
                                                        'Turning off this table will stop the webhook from consuming any more data. When you re-enable it, a full refresh sync will need to be completed to ensure no data is missing.',
                                                    primaryButton: {
                                                        children: 'Disable',
                                                        status: 'danger',
                                                        onClick: () => updateSchema({ ...schema, should_sync: false }),
                                                    },
                                                    secondaryButton: {
                                                        children: 'Cancel',
                                                    },
                                                })
                                            } else {
                                                updateSchema({ ...schema, should_sync: active })
                                            }
                                        }}
                                    />
                                </SourceEditorAction>
                            )
                        },
                    },
                    {
                        title: 'Synced Table',
                        key: 'table',
                        isHidden: isDirectQuerySource,
                        render: function RenderTable(_, schema) {
                            if (schema.table) {
                                const query = defaultQuery(schema.table.name, schema.table.columns)
                                return (
                                    <Link
                                        to={urls.sqlEditor({ query: query.source.query })}
                                        onClick={(event) => {
                                            event.preventDefault()
                                            newInternalTab(urls.sqlEditor({ query: query.source.query }))
                                        }}
                                    >
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
                        isHidden: isDirectQuerySource,
                        render: function Render(_, schema) {
                            return schema.last_synced_at ? (
                                <>
                                    <TZLabel
                                        time={schema.last_synced_at}
                                        formatDate="MMM DD, YYYY"
                                        formatTime="HH:mm"
                                    />
                                </>
                            ) : null
                        },
                    },
                    {
                        title: 'Rows Synced',
                        key: 'rows_synced',
                        isHidden: isDirectQuerySource,
                        render: function Render(_, schema) {
                            if (schema.table) {
                                return schema.table.row_count?.toLocaleString() ?? 0
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
                        isHidden: isDirectQuerySource,
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
                                <Tooltip title={schema.latest_error} interactive>
                                    {tagContent}
                                </Tooltip>
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
                                    <SourceEditorAction source={source}>
                                        {({ disabledReason }) => (
                                            <More
                                                disabledReason={disabledReason}
                                                overlay={
                                                    isDirectQuerySource ? (
                                                        <>
                                                            {schema.table && (
                                                                <LemonButton
                                                                    type="tertiary"
                                                                    size="xsmall"
                                                                    fullWidth
                                                                    onClick={() => {
                                                                        const table = schema.table
                                                                        if (!table) {
                                                                            return
                                                                        }

                                                                        newInternalTab(getPreviewUrl(table.name))
                                                                    }}
                                                                >
                                                                    Open in SQL editor
                                                                </LemonButton>
                                                            )}
                                                            <LemonButton
                                                                id="data-warehouse-schema-toggle-visibility"
                                                                type="tertiary"
                                                                fullWidth
                                                                size="xsmall"
                                                                status={schema.should_sync ? 'danger' : 'default'}
                                                                onClick={() =>
                                                                    updateSchema({
                                                                        ...schema,
                                                                        should_sync: !schema.should_sync,
                                                                    })
                                                                }
                                                                disabledReason={disabledReason}
                                                            >
                                                                {schema.should_sync ? 'Hide table' : 'Enable table'}
                                                            </LemonButton>
                                                        </>
                                                    ) : (
                                                        <>
                                                            <Tooltip
                                                                title={
                                                                    schema.sync_type === 'cdc'
                                                                        ? 'Trigger a CDC extraction run now.'
                                                                        : schema.incremental
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
                                                                    onClick={() => reloadSchema(schema)}
                                                                    disabledReason={disabledReason}
                                                                >
                                                                    {schema.sync_type === 'cdc'
                                                                        ? 'Sync CDC now'
                                                                        : 'Sync now'}
                                                                </LemonButton>
                                                            </Tooltip>
                                                            {schema.sync_type === 'cdc' && (
                                                                <Tooltip title="Re-snapshot the full table and replay all CDC changes on top. Use this to recover from a corrupted or out-of-sync table.">
                                                                    <LemonButton
                                                                        type="tertiary"
                                                                        size="xsmall"
                                                                        fullWidth
                                                                        key={`resync-data-warehouse-schema-${schema.id}`}
                                                                        id="data-warehouse-schema-resync"
                                                                        onClick={() => {
                                                                            const hasCdcTable =
                                                                                schema.cdc_table_mode === 'cdc_only' ||
                                                                                schema.cdc_table_mode === 'both'
                                                                            LemonDialog.open({
                                                                                title: 'Full resync — all existing data will be replaced',
                                                                                content: (
                                                                                    <div className="text-sm text-secondary space-y-2">
                                                                                        <p>
                                                                                            This will re-snapshot the
                                                                                            entire table from the source
                                                                                            database. All rows currently
                                                                                            in the{' '}
                                                                                            <strong>
                                                                                                {schema.table?.name ??
                                                                                                    schema.name}
                                                                                            </strong>{' '}
                                                                                            table will be replaced with
                                                                                            the new snapshot.
                                                                                        </p>
                                                                                        {hasCdcTable && (
                                                                                            <p>
                                                                                                The{' '}
                                                                                                <strong>
                                                                                                    {(schema.table
                                                                                                        ?.name ??
                                                                                                        schema.name) +
                                                                                                        '_cdc'}
                                                                                                </strong>{' '}
                                                                                                history table will also
                                                                                                be reset — all change
                                                                                                history will be lost and
                                                                                                replaced with the new
                                                                                                snapshot as the starting
                                                                                                point.
                                                                                            </p>
                                                                                        )}
                                                                                    </div>
                                                                                ),
                                                                                primaryButton: {
                                                                                    children: 'Full resync',
                                                                                    status: 'danger',
                                                                                    onClick: () => resyncSchema(schema),
                                                                                },
                                                                                secondaryButton: {
                                                                                    children: 'Cancel',
                                                                                    type: 'tertiary',
                                                                                },
                                                                            })
                                                                        }}
                                                                        status="danger"
                                                                        disabledReason={disabledReason}
                                                                    >
                                                                        Full resync
                                                                    </LemonButton>
                                                                </Tooltip>
                                                            )}
                                                            {schema.status === 'Running' && (
                                                                <LemonButton
                                                                    type="tertiary"
                                                                    size="xsmall"
                                                                    fullWidth
                                                                    status="danger"
                                                                    onClick={() => cancelSchema(schema)}
                                                                    disabledReason={disabledReason}
                                                                >
                                                                    Cancel sync
                                                                </LemonButton>
                                                            )}
                                                            {(schema.incremental || schema.sync_type === 'webhook') && (
                                                                <Tooltip title="Completely resync data by deleting the existing table and re-importing. Only recommended if there is an issue with data quality in previously imported data.">
                                                                    <LemonButton
                                                                        type="tertiary"
                                                                        size="xsmall"
                                                                        fullWidth
                                                                        key={`resync-data-warehouse-schema-${schema.id}`}
                                                                        id="data-warehouse-schema-resync"
                                                                        onClick={() => resyncSchema(schema)}
                                                                        status="danger"
                                                                        disabledReason={disabledReason}
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
                                                                        disabledReason={disabledReason}
                                                                    >
                                                                        Delete table from PostHog
                                                                    </LemonButton>
                                                                </Tooltip>
                                                            )}
                                                        </>
                                                    )
                                                }
                                            />
                                        )}
                                    </SourceEditorAction>
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
    const logic = syncMethodModalLogic({ schema })

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
    }, [currentSyncMethodModalSchema?.id, resetSchemaIncrementalFields, loadSchemaIncrementalFields])

    const schemaLoading = schemaIncrementalFieldsLoading || !schemaIncrementalFields
    const showForm = !schemaLoading && schemaIncrementalFields

    if (!currentSyncMethodModalSchema) {
        return <></>
    }

    return (
        <LemonModal
            title={
                <>
                    Sync method for{' '}
                    <span className="font-mono">
                        {currentSyncMethodModalSchema.label ?? currentSyncMethodModalSchema.name}
                    </span>
                </>
            }
            isOpen={syncMethodModalIsOpen}
            onClose={closeSyncMethodModal}
            footer={
                schemaLoading ? (
                    <>
                        <LemonSkeleton.Button />
                        <LemonSkeleton.Button />
                    </>
                ) : null
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
                        description: currentSyncMethodModalSchema.description,
                        should_sync_default: currentSyncMethodModalSchema.should_sync_default ?? true,
                        sync_type: currentSyncMethodModalSchema.sync_type,
                        sync_time_of_day: currentSyncMethodModalSchema.sync_time_of_day ?? null,
                        incremental_field: currentSyncMethodModalSchema.incremental_field ?? null,
                        incremental_field_type: currentSyncMethodModalSchema.incremental_field_type ?? null,
                        incremental_available: schemaIncrementalFields.incremental_available,
                        append_available: schemaIncrementalFields.append_available,
                        cdc_available: schemaIncrementalFields.cdc_available,
                        cdc_table_mode: currentSyncMethodModalSchema.cdc_table_mode,
                        incremental_fields: schemaIncrementalFields.incremental_fields,
                        supports_webhooks: schemaIncrementalFields?.supports_webhooks ?? false,
                        primary_key_columns: currentSyncMethodModalSchema.primary_key_columns ?? null,
                        available_columns: [],
                        detected_primary_keys: null,
                    }}
                    availableColumns={schemaIncrementalFields.available_columns ?? []}
                    detectedPrimaryKeys={schemaIncrementalFields.detected_primary_keys ?? null}
                    primaryKeyLocked={!!currentSyncMethodModalSchema.table}
                    onClose={() => {
                        resetSchemaIncrementalFields()
                        closeSyncMethodModal()
                    }}
                    onSave={(syncType, incrementalField, incrementalFieldType, primaryKeyColumns, cdcTableMode) => {
                        const noIncrementalField = syncType === 'full_refresh' || syncType === 'cdc'
                        updateSchema({
                            ...currentSyncMethodModalSchema,
                            should_sync: true,
                            sync_type: syncType,
                            incremental_field: noIncrementalField ? null : incrementalField,
                            incremental_field_type: noIncrementalField ? null : incrementalFieldType,
                            sync_time_of_day: currentSyncMethodModalSchema.sync_time_of_day ?? null,
                            primary_key_columns: syncType === 'incremental' ? (primaryKeyColumns ?? null) : null,
                            ...(syncType === 'cdc' && cdcTableMode ? { cdc_table_mode: cdcTableMode } : {}),
                        })
                    }}
                />
            )}
        </LemonModal>
    )
}

const AnchorTime = ({
    schema,
    disabledReason,
    isProjectTime,
    updateSchema,
}: {
    schema: ExternalDataSourceSchema
    disabledReason: string | null
    isProjectTime: boolean
    updateSchema: (schema: ExternalDataSourceSchema) => void
}): JSX.Element => {
    const { currentTeam } = useValues(teamLogic)
    const [isSyncTimeSet, setIsSyncTimeSet] = useState(!!schema.sync_time_of_day)

    const utcTime = schema.sync_time_of_day || '00:00:00'
    const localTime = isProjectTime
        ? dayjs
              .utc(`${dayjs().format('YYYY-MM-DD')}T${utcTime}`)
              .local()
              .tz(currentTeam?.timezone || 'UTC')
              .format('HH:mm:00')
        : utcTime

    const disabledReasonForInput = useCallback((): string | undefined => {
        if (disabledReason) {
            return disabledReason
        }

        if (!schema.should_sync && !isSyncTimeSet) {
            return 'Enable syncing and anchor times to set anchor time'
        }

        if (!schema.should_sync) {
            return 'Enable syncing to set anchor time'
        }

        if (!isSyncTimeSet) {
            return 'Enable anchor times to set anchor time'
        }

        if (
            schema.sync_frequency === '5min' ||
            schema.sync_frequency === '30min' ||
            schema.sync_frequency === '1hour'
        ) {
            return 'Anchor time does not apply to sync intervals one hour or less'
        }

        return undefined
    }, [disabledReason, isSyncTimeSet, schema.should_sync, schema.sync_frequency])

    return (
        <div className="flex">
            <LemonInput
                type="time"
                size="xsmall"
                disabledReason={disabledReasonForInput()}
                value={isSyncTimeSet ? localTime.substring(0, 5) : undefined}
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
                    isSyncTimeSet ? (
                        <Tooltip title={syncAnchorIntervalToHumanReadable(utcTime, schema.sync_frequency)}>
                            {schema.should_sync && <IconInfo className="text-muted-alt" />}
                        </Tooltip>
                    ) : undefined
                }
            />
            <LemonSwitch
                className="ml-2"
                checked={isSyncTimeSet}
                disabledReason={disabledReason || (!schema.should_sync && 'Enable syncing to set anchor time')}
                onChange={(checked) => {
                    setIsSyncTimeSet(checked)
                    updateSchema({
                        ...schema,
                        sync_time_of_day: checked ? (isProjectTime ? localTime : utcTime) : null,
                    })
                }}
            />
        </div>
    )
}
