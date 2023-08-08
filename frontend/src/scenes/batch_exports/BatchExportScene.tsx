import { SceneExport } from 'scenes/sceneTypes'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonButton } from '@posthog/lemon-ui'
import { urls } from 'scenes/urls'
import { useActions, useValues } from 'kea'
import { useEffect } from 'react'
import { BatchExportLogicProps, batchExportLogic } from './batchExportLogic'

export const scene: SceneExport = {
    component: BatchExportScene,
    logic: batchExportLogic,
    paramsToProps: ({ params: { id } }: { params: { id?: string } }): BatchExportLogicProps => ({
        id: id ?? 'missing',
    }),
}

export function BatchExportScene(): JSX.Element {
    const { batchExportConfig, batchExportConfigLoading } = useValues(batchExportLogic)
    const { loadBatchExportConfig } = useActions(batchExportLogic)

    useEffect(() => {
        loadBatchExportConfig()
    }, [])

    return (
        <>
            <PageHeader
                title={batchExportConfig?.name ?? (batchExportConfigLoading ? 'Loading...' : 'Missing')}
                buttons={
                    batchExportConfig ? (
                        <>
                            <LemonButton type="primary" to={urls.batchExportEdit(batchExportConfig?.id)}>
                                Edit
                            </LemonButton>
                        </>
                    ) : undefined
                }
            />

            {/* <LemonTable
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
                            return (
                                <LemonTag type={batchExport.paused ? 'default' : 'primary'} className="uppercase">
                                    {batchExport.paused ? 'Paused' : 'Active'}
                                </LemonTag>
                            )
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
            /> */}
        </>
    )
}
