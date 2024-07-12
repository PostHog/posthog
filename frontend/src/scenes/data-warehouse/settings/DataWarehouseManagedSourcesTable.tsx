import { TZLabel } from '@posthog/apps-common'
import { LemonButton, LemonDialog, LemonTable, LemonTag, Link, Spinner, Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import cloudflareLogo from 'public/cloudflare-logo.svg'
import googleStorageLogo from 'public/google-cloud-storage-logo.png'
import hubspotLogo from 'public/hubspot-logo.svg'
import postgresLogo from 'public/postgres-logo.svg'
import s3Logo from 'public/s3-logo.png'
import snowflakeLogo from 'public/snowflake-logo.svg'
import stripeLogo from 'public/stripe-logo.svg'
import zendeskLogo from 'public/zendesk-logo.svg'
import { urls } from 'scenes/urls'

import { manualLinkSources, ProductKey } from '~/types'

import { dataWarehouseSettingsLogic } from './dataWarehouseSettingsLogic'

const StatusTagSetting = {
    Running: 'primary',
    Completed: 'success',
    Error: 'danger',
    Failed: 'danger',
}

export function DataWarehouseManagedSourcesTable(): JSX.Element {
    const { dataWarehouseSources, dataWarehouseSourcesLoading, sourceReloadingById, currentTab } =
        useValues(dataWarehouseSettingsLogic)
    const { deleteSource, reloadSource } = useActions(dataWarehouseSettingsLogic)

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
                    title: 'Source',
                    key: 'name',
                    render: function RenderName(_, source) {
                        return (
                            <LemonTableLink
                                to={urls.dataWarehouseSourceSettings(source.id, currentTab)}
                                title={source.source_type}
                                description={source.prefix}
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
                        return source.schemas
                            .reduce((acc, schema) => acc + (schema.table?.row_count ?? 0), 0)
                            .toLocaleString()
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
