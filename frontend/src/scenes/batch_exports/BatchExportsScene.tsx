import { SceneExport } from 'scenes/sceneTypes'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonButton, LemonTable, Link } from '@posthog/lemon-ui'
import { urls } from 'scenes/urls'
import { useActions, useValues } from 'kea'
import { batchExportsListLogic } from './batchExportsListLogic'
import { LemonMenu, LemonMenuItems } from 'lib/lemon-ui/LemonMenu'
import { IconEllipsis } from 'lib/lemon-ui/icons'
import { useEffect } from 'react'
import { BatchExportTag } from './components'

export const scene: SceneExport = {
    component: BatchExportsScene,
}

export function BatchExportsScene(): JSX.Element {
    const { batchExportConfigs, batchExportConfigsLoading } = useValues(batchExportsListLogic)
    const { loadBatchExports } = useActions(batchExportsListLogic)

    useEffect(() => {
        loadBatchExports()
    }, [])

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

            <LemonTable
                dataSource={batchExportConfigs}
                loading={batchExportConfigsLoading}
                columns={[
                    {
                        title: 'Name',
                        key: 'name',
                        render: function RenderName(_, batchExport) {
                            return (
                                <Link className="font-semibold" to={urls.batchExport(batchExport.id)}>
                                    {batchExport.name}
                                </Link>
                            )
                        },
                    },
                    {
                        title: 'Runs',
                        key: 'runs',
                        render: function RenderStatus(_, batchExport) {
                            return (
                                <div className="flex gap-2">
                                    {batchExport.runs?.map((run) => (
                                        <div key={run.id} className="flex gap-1" title={run.status}>
                                            <span>{run.status === 'Failed' ? '🔴' : '🟢'}</span>
                                        </div>
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
                                    status: batchExport.paused ? 'primary' : 'danger',
                                    onClick: () => {},
                                },
                            ]
                            return (
                                <LemonMenu items={menuItems} placement="left">
                                    <LemonButton size="small" status="stealth" noPadding icon={<IconEllipsis />} />
                                </LemonMenu>
                            )
                        },
                    },
                ]}
            />
        </>
    )
}
