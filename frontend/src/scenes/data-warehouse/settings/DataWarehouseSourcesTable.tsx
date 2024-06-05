import { TZLabel } from '@posthog/apps-common'
import { LemonButton, LemonDialog, LemonSwitch, LemonTable, LemonTag, Link, Spinner, Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { More } from 'lib/lemon-ui/LemonButton/More'
import hubspotLogo from 'public/hubspot-logo.svg'
import postgresLogo from 'public/postgres-logo.svg'
import posthogLogo from 'public/posthog-icon.svg'
import stripeLogo from 'public/stripe-logo.svg'
import zendeskLogo from 'public/zendesk-logo.svg'
import { urls } from 'scenes/urls'

import { DataTableNode, NodeKind } from '~/queries/schema'
import {
    ExternalDataSourceSchema,
    ExternalDataSourceType,
    ExternalDataStripeSource,
    PipelineInterval,
    ProductKey,
} from '~/types'

import { dataWarehouseSettingsLogic } from './dataWarehouseSettingsLogic'

const StatusTagSetting = {
    Running: 'primary',
    Completed: 'success',
    Error: 'danger',
    Failed: 'danger',
}

export function DataWarehouseSourcesTable(): JSX.Element {
    const { dataWarehouseSources, dataWarehouseSourcesLoading, sourceReloadingById } =
        useValues(dataWarehouseSettingsLogic)
    const { deleteSource, reloadSource } = useActions(dataWarehouseSettingsLogic)

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
                        return <RenderDataWarehouseSourceIcon type={source.source_type as ExternalDataSourceType} />
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
                    title: 'Table Prefix',
                    key: 'prefix',
                    render: function RenderPrefix(_, source) {
                        return source.prefix
                    },
                },
                {
                    title: 'Sync Frequency',
                    key: 'frequency',
                    render: function RenderFrequency() {
                        return 'day' as PipelineInterval
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

export function getDataWarehouseSourceUrl(service: ExternalDataSourceType): string {
    return `https://posthog.com/docs/data-warehouse/setup#${service.toLowerCase()}`
}

export function RenderDataWarehouseSourceIcon({
    type,
    size = 'small',
}: {
    type: ExternalDataSourceType
    size?: 'small' | 'medium'
}): JSX.Element {
    const sizePx = size === 'small' ? 30 : 60

    if (type == 'Manual') {
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
                    <Link to="https://posthog.com/docs/data-warehouse/setup#linking-a-custom-source">
                        <img src={posthogLogo} alt={type} height={sizePx} width={sizePx} />
                    </Link>
                </Tooltip>
            </div>
        )
    }

    const icon = {
        Stripe: stripeLogo,
        Hubspot: hubspotLogo,
        Zendesk: zendeskLogo,
        Postgres: postgresLogo,
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
                    title: 'Refresh Type',
                    key: 'incremental',
                    render: function RenderIncremental(_, schema) {
                        return schema.incremental ? (
                            <Tooltip title="Each run will only pull data that has since been added" placement="top">
                                <LemonTag type="primary">Incremental</LemonTag>
                            </Tooltip>
                        ) : (
                            <Tooltip title="Each run will pull all data from the source" placement="top">
                                <LemonTag type="default">Full Refresh</LemonTag>
                            </Tooltip>
                        )
                    },
                },
                {
                    title: 'Enabled',
                    key: 'should_sync',
                    render: function RenderShouldSync(_, schema) {
                        return (
                            <LemonSwitch
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
                                <Link to={urls.insightNew(undefined, undefined, JSON.stringify(query))}>
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
                                <TZLabel time={schema.last_synced_at} formatDate="MMM DD, YYYY" formatTime="HH:mm" />
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

                        return <LemonTag type={StatusTagSetting[schema.status] || 'default'}>{schema.status}</LemonTag>
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
    )
}
