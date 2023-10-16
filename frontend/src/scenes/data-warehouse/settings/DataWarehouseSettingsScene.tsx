import { LemonButton, LemonMenu, LemonMenuItems, LemonTable, LemonTag } from '@posthog/lemon-ui'
import { PageHeader } from 'lib/components/PageHeader'
import { SceneExport } from 'scenes/sceneTypes'
import { dataWarehouseSettingsLogic } from './dataWarehouseSettingsLogic'
import { useValues } from 'kea'
import { IconEllipsis } from 'lib/lemon-ui/icons'

export const scene: SceneExport = {
    component: DataWarehouseSettingsScene,
    logic: dataWarehouseSettingsLogic,
}

export function DataWarehouseSettingsScene(): JSX.Element {
    const { dataWarehouseSources, dataWarehouseSourcesLoading } = useValues(dataWarehouseSettingsLogic)

    return (
        <div>
            <PageHeader
                title={
                    <div className="flex items-center gap-2">
                        Data Warehouse
                        <LemonTag type="warning" className="uppercase">
                            Beta
                        </LemonTag>
                    </div>
                }
            />
            <LemonTable
                dataSource={dataWarehouseSources?.results ?? []}
                loading={dataWarehouseSourcesLoading}
                columns={[
                    {
                        title: 'Name',
                        key: 'name',
                        width: 0,
                        render: function RenderName() {
                            return ''
                        },
                    },
                    {
                        title: 'Source',
                        key: 'source',
                        render: function RenderType() {
                            return <>{'some source'}</>
                        },
                    },
                    {
                        title: 'Status',
                        key: 'status',
                        width: 0,
                        render: function RenderStatus() {
                            return 'Something'
                        },
                    },

                    {
                        width: 0,
                        render: function Render() {
                            const menuItems: LemonMenuItems = []
                            return (
                                <LemonMenu items={menuItems} placement="left">
                                    <LemonButton size="small" status="stealth" noPadding icon={<IconEllipsis />} />
                                </LemonMenu>
                            )
                        },
                    },
                ]}
            />
        </div>
    )
}
