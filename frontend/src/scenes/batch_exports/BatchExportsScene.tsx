import { SceneExport } from 'scenes/sceneTypes'
import { BatchExport } from './api'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonButton, LemonTable, LemonTag, Link } from '@posthog/lemon-ui'
import { urls } from 'scenes/urls'
import { useActions, useValues } from 'kea'
import { batchExportsListLogic } from './batchExportsListLogic'
import { LemonMenu, LemonMenuItems } from 'lib/lemon-ui/LemonMenu'
import { IconEllipsis } from 'lib/lemon-ui/icons'
import { useEffect } from 'react'

export const scene: SceneExport = {
    component: BatchExportsScene,
}

export interface ExportActionButtonsProps {
    currentTeamId: number
    export_: BatchExport
    loading: boolean
    buttonFullWidth: boolean
    buttonType: 'primary' | 'secondary' | 'tertiary'
    dividerVertical: boolean
    updateCallback: (signal: AbortSignal | undefined) => void
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
                            return <Link to={urls.batchExport(batchExport.id)}>{batchExport.name}</Link>
                        },
                    },
                    {
                        title: 'Type',
                        key: 'type',
                        render: function RenderType(_, batchExport) {
                            return <>{batchExport.destination.type}</>
                        },
                    },
                    {
                        title: 'Status',
                        key: 'status',
                        render: function RenderStatus(_, batchExport) {
                            return (
                                <LemonTag type={batchExport.paused ? 'default' : 'primary'} className="uppercase">
                                    {batchExport.paused ? 'Paused' : 'Active'}
                                </LemonTag>
                            )
                        },
                    },
                    {
                        title: 'Frequency',
                        key: 'frequency',
                        dataIndex: 'interval',
                    },
                    {
                        render: function Render(_, batchExport) {
                            const menuItems: LemonMenuItems = []
                            return (
                                <LemonMenu items={menuItems}>
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
