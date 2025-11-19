import { useActions, useValues } from 'kea'

import {
    LemonButton,
    LemonDialog,
    LemonInput,
    LemonSkeleton,
    LemonTable,
    LemonTag,
    Spinner,
    Tooltip,
} from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { DataWarehouseSourceIcon } from 'scenes/data-warehouse/settings/DataWarehouseSourceIcon'
import { StatusTagSetting } from 'scenes/data-warehouse/utils'
import { urls } from 'scenes/urls'

import FireSaleBanner from '../FireSaleBanner'
import { availableSourcesDataLogic } from '../new/availableSourcesDataLogic'
import { dataWarehouseSettingsLogic } from './dataWarehouseSettingsLogic'

export function DataWarehouseManagedSourcesTable(): JSX.Element {
    const { filteredManagedSources, dataWarehouseSourcesLoading, sourceReloadingById, managedSearchTerm } =
        useValues(dataWarehouseSettingsLogic)
    const { deleteSource, reloadSource, setManagedSearchTerm } = useActions(dataWarehouseSettingsLogic)
    const { availableSources, availableSourcesLoading } = useValues(availableSourcesDataLogic)

    if (availableSourcesLoading || !availableSources) {
        return <LemonSkeleton />
    }

    return (
        <div>
            <FireSaleBanner />
            <div className="flex gap-2 justify-between items-center mb-4">
                <LemonInput
                    type="search"
                    placeholder="Search..."
                    onChange={setManagedSearchTerm}
                    value={managedSearchTerm}
                />
            </div>
            <LemonTable
                id="managed-sources"
                dataSource={filteredManagedSources}
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
                                to={urls.dataWarehouseSource(`managed-${source.id}`)}
                                title={availableSources[source.source_type]?.label ?? source.source_type}
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
        </div>
    )
}

const DOCS_BASE_URL = 'https://posthog.com/docs/cdp/sources/'

export function getDataWarehouseSourceUrl(service: string): string {
    switch (service) {
        case 'aws':
            return `${DOCS_BASE_URL}s3`
        case 'google-cloud':
            return `${DOCS_BASE_URL}gcs`
        case 'azure':
            return `${DOCS_BASE_URL}azure-blob`
        case 'cloudflare-r2':
            return `${DOCS_BASE_URL}r2`
        default:
            return `${DOCS_BASE_URL}${service.toLowerCase()}`
    }
}
