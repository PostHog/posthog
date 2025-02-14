import { LemonButton, LemonDialog, LemonTable, Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { TZLabel } from 'lib/components/TZLabel'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { dataWarehouseTableLogic } from 'scenes/data-warehouse/new/dataWarehouseTableLogic'
import { DataWarehouseSourceIcon, mapUrlToProvider } from 'scenes/data-warehouse/settings/DataWarehouseSourceIcon'
import { urls } from 'scenes/urls'

import { PipelineNodeTab, PipelineStage } from '~/types'

import { dataWarehouseSettingsLogic } from './dataWarehouseSettingsLogic'

export function DataWarehouseSelfManagedSourcesTable(): JSX.Element {
    const { deleteSelfManagedTable, refreshSelfManagedTableSchema } = useActions(dataWarehouseSettingsLogic)
    const { tables } = useValues(dataWarehouseTableLogic())

    return (
        <LemonTable
            dataSource={tables}
            pagination={{ pageSize: 10 }}
            columns={[
                {
                    width: 0,
                    render: (_, item) => <DataWarehouseSourceIcon type={mapUrlToProvider(item.url_pattern)} />,
                },
                {
                    title: 'Source',
                    dataIndex: 'name',
                    key: 'name',
                    render: (_, item) => (
                        <LemonTableLink
                            to={urls.pipelineNode(
                                PipelineStage.Source,
                                `self-managed-${item.id}`,
                                PipelineNodeTab.SourceConfiguration
                            )}
                            title={item.name}
                        />
                    ),
                },
                {
                    title: 'Created at',
                    dataIndex: 'created_at',
                    key: 'created_at',
                    render: (_, item) => {
                        return item.created_at ? (
                            <TZLabel time={item.created_at} formatDate="MMM DD, YYYY" formatTime="HH:mm" />
                        ) : (
                            'N/A'
                        )
                    },
                },
                {
                    title: 'Format',
                    dataIndex: 'format',
                    key: 'format',
                    render: (_, item) => item.format,
                },
                {
                    key: 'actions',
                    width: 0,
                    render: (_, item) => (
                        <div className="flex flex-row justify-end">
                            <div>
                                <More
                                    overlay={
                                        <>
                                            <Tooltip title="Update schema from source">
                                                <LemonButton
                                                    data-attr={`refresh-data-warehouse-${item.name}`}
                                                    key={`refresh-data-warehouse-${item.name}`}
                                                    onClick={() => refreshSelfManagedTableSchema(item.id)}
                                                >
                                                    Reload
                                                </LemonButton>
                                            </Tooltip>
                                            <LemonButton
                                                status="danger"
                                                data-attr={`delete-data-warehouse-${item.name}`}
                                                key={`delete-data-warehouse-${item.name}`}
                                                onClick={() => {
                                                    LemonDialog.open({
                                                        title: 'Delete table?',
                                                        description:
                                                            'Table deletion cannot be undone. All views and joins related to this table will be deleted.',

                                                        primaryButton: {
                                                            children: 'Delete',
                                                            status: 'danger',
                                                            onClick: () => {
                                                                deleteSelfManagedTable(item.id)
                                                            },
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
                        </div>
                    ),
                },
            ]}
        />
    )
}
