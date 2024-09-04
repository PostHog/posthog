import { TZLabel } from '@posthog/apps-common'
import { LemonButton, LemonDialog, LemonTable, LemonTag, Link, Spinner, Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import IconAwsS3 from 'public/services/aws-s3.png'
import Iconazure from 'public/services/azure.png'
import IconCloudflare from 'public/services/cloudflare.png'
import IconGoogleCloudStorage from 'public/services/google-cloud-storage.png'
import IconHubspot from 'public/services/hubspot.png'
import IconMySQL from 'public/services/mysql.png'
import IconPostgres from 'public/services/postgres.png'
import IconSalesforce from 'public/services/salesforce.png'
import IconSnowflake from 'public/services/snowflake.png'
import IconMSSQL from 'public/services/sql-azure.png'
import IconStripe from 'public/services/stripe.png'
import IconZendesk from 'public/services/zendesk.png'
import { urls } from 'scenes/urls'

import { manualLinkSources, PipelineNodeTab, PipelineStage } from '~/types'

import { SOURCE_DETAILS } from '../new/sourceWizardLogic'
import { dataWarehouseSettingsLogic } from './dataWarehouseSettingsLogic'

const StatusTagSetting = {
    Running: 'primary',
    Completed: 'success',
    Error: 'danger',
    Failed: 'danger',
    'Billing limits': 'danger',
}

export function DataWarehouseManagedSourcesTable(): JSX.Element {
    const { dataWarehouseSources, dataWarehouseSourcesLoading, sourceReloadingById } =
        useValues(dataWarehouseSettingsLogic)
    const { deleteSource, reloadSource } = useActions(dataWarehouseSettingsLogic)

    return (
        <LemonTable
            dataSource={dataWarehouseSources?.results ?? []}
            loading={dataWarehouseSourcesLoading}
            disableTableWhileLoading={false}
            pagination={{ pageSize: 10 }}
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
                                to={urls.pipelineNode(
                                    PipelineStage.Source,
                                    `managed-${source.id}`,
                                    PipelineNodeTab.Schemas
                                )}
                                title={SOURCE_DETAILS[source.source_type]?.label ?? source.source_type}
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
        Stripe: IconStripe,
        Hubspot: IconHubspot,
        Zendesk: IconZendesk,
        Postgres: IconPostgres,
        MySQL: IconMySQL,
        Snowflake: IconSnowflake,
        aws: IconAwsS3,
        'google-cloud': IconGoogleCloudStorage,
        'cloudflare-r2': IconCloudflare,
        azure: Iconazure,
        Salesforce: IconSalesforce,
        MSSQL: IconMSSQL,
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
                    <img src={icon} alt={type} height={sizePx} width={sizePx} className="rounded" />
                </Link>
            </Tooltip>
        </div>
    )
}
