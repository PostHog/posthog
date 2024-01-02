import { LemonButton, LemonTable, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { IconEllipsis } from 'lib/lemon-ui/icons'
import { LemonMenu, LemonMenuItems } from 'lib/lemon-ui/LemonMenu'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { batchExportsListLogic } from './batchExportsListLogic'
import { BatchExportRunIcon, BatchExportTag } from './components'

export const scene: SceneExport = {
    component: BatchExportsListScene,
}

export function BatchExportsListScene(): JSX.Element {
    return (
        <>
            <PageHeader
                title="Batch Exports"
                buttons={
                    <>
                        <LemonButton type="primary" to={urls.batchExportNew()}>
                            Create export workflow
                        </LemonButton>
                    </>
                }
            />
            <p>Batch exports allow you to export your data to a destination of your choice.</p>

            <BatchExportsList />
        </>
    )
}

export function BatchExportsList(): JSX.Element {
    const { batchExportConfigs, batchExportConfigsLoading, pagination } = useValues(batchExportsListLogic)
    const { unpause, pause } = useActions(batchExportsListLogic)

    return (
        <>
            <LemonTable
                dataSource={batchExportConfigs?.results ?? []}
                loading={batchExportConfigsLoading}
                pagination={pagination}
                columns={[
                    {
                        title: 'Name',
                        key: 'name',
                        width: 0,
                        render: function RenderName(_, batchExport) {
                            return (
                                <Link className="font-semibold truncate" to={urls.batchExport(batchExport.id)}>
                                    {batchExport.name}
                                </Link>
                            )
                        },
                    },
                    {
                        title: 'Latest runs',
                        key: 'runs',
                        render: function RenderStatus(_, batchExport) {
                            return (
                                <div className="flex gap-2">
                                    {[...(batchExport.latest_runs || [])].reverse()?.map((run) => (
                                        // TODO: Link to run details
                                        <LemonButton
                                            to={urls.batchExport(batchExport.id)}
                                            key={run.id}
                                            className="flex gap-1"
                                            noPadding
                                        >
                                            <BatchExportRunIcon runs={[run]} />
                                        </LemonButton>
                                    ))}
                                </div>
                            )
                        },
                    },

                    {
                        title: 'Destination',
                        key: 'destination',
                        render: function RenderType(_, batchExport) {
                            return <>{batchExport.destination.type}</>
                        },
                    },

                    {
                        title: 'Frequency',
                        key: 'frequency',
                        dataIndex: 'interval',
                    },
                    {
                        title: 'Status',
                        key: 'status',
                        width: 0,
                        render: function RenderStatus(_, batchExport) {
                            return <BatchExportTag batchExportConfig={batchExport} />
                        },
                    },

                    {
                        width: 0,
                        render: function Render(_, batchExport) {
                            const menuItems: LemonMenuItems = [
                                {
                                    label: 'View',
                                    to: urls.batchExport(batchExport.id),
                                },
                                {
                                    label: 'Edit',
                                    to: urls.batchExportEdit(batchExport.id),
                                },
                                {
                                    label: batchExport.paused ? 'Resume' : 'Pause',
                                    status: batchExport.paused ? 'default' : 'danger',
                                    onClick: () => {
                                        batchExport.paused ? unpause(batchExport) : pause(batchExport)
                                    },
                                },
                            ]
                            return (
                                <LemonMenu items={menuItems} placement="left">
                                    <LemonButton size="small" noPadding icon={<IconEllipsis />} />
                                </LemonMenu>
                            )
                        },
                    },
                ]}
            />
        </>
    )
}
