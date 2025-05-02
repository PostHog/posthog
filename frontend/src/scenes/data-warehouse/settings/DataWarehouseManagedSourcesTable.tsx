import { LemonButton, LemonDialog, LemonTable, LemonTag, Spinner, Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { TZLabel } from 'lib/components/TZLabel'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { DataWarehouseSourceIcon } from 'scenes/data-warehouse/settings/DataWarehouseSourceIcon'
import { urls } from 'scenes/urls'

import { manualLinkSources, PipelineNodeTab, PipelineStage } from '~/types'

import { SOURCE_DETAILS } from '../new/sourceWizardLogic'
import { dataWarehouseSettingsLogic } from './dataWarehouseSettingsLogic'

export const StatusTagSetting: Record<string, 'primary' | 'success' | 'danger'> = {
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
            id="managed-sources"
            dataSource={dataWarehouseSources?.results ?? []}
            loading={dataWarehouseSourcesLoading}
            disableTableWhileLoading={false}
            pagination={{ pageSize: 10 }}
            columns={[
                {
                    width: 0,
                    render: (_, source) => <DataWarehouseSourceIcon type={source.source_type} />,
                },
                {
                    title: 'Source',
                    key: 'name',
                    render: (_, source) => (
                        <LemonTableLink
                            to={urls.pipelineNode(
                                PipelineStage.Source,
                                `managed-${source.id}`,
                                PipelineNodeTab.Schemas
                            )}
                            title={SOURCE_DETAILS[source.source_type]?.label ?? source.source_type}
                            description={source.prefix}
                        />
                    ),
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
                    render: (_, source) =>
                        source.schemas
                            .reduce((acc, schema) => acc + (schema.table?.row_count ?? 0), 0)
                            .toLocaleString(),
                },
                {
                    title: 'Status',
                    key: 'status',
                    render: (_, source) => {
                        if (!source.status) {
                            return null
                        }
                        const tagContent = (
                            <LemonTag type={StatusTagSetting[source.status] || 'default'}>{source.status}</LemonTag>
                        )
                        return source.latest_error && source.status === 'Error' ? (
                            <Tooltip title={source.latest_error}>{tagContent}</Tooltip>
                        ) : (
                            tagContent
                        )
                    },
                },
                {
                    key: 'actions',
                    width: 0,
                    render: (_, source) => (
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
                    ),
                },
            ]}
        />
    )
}

export function getDataWarehouseSourceUrl(service: string): string {
    if (manualLinkSources.includes(service)) {
        return 'https://posthog.com/docs/cdp/sources/s3'
    }

    return `https://posthog.com/docs/cdp/sources/${service.toLowerCase()}`
}
