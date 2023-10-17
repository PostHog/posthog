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
                        title: 'Source Type',
                        key: 'name',
                        width: 0,
                        render: function RenderName(_, source) {
                            return source.source_type
                        },
                    },
                    {
                        title: 'Status',
                        key: 'status',
                        width: 0,
                        render: function RenderStatus(_, source) {
                            return <LemonTag type="primary">{source.status}</LemonTag>
                        },
                    },

                    {
                        width: 0,
                        render: function Render() {
                            const menuItems: LemonMenuItems = [
                                {
                                    label: 'Remove',
                                    status: 'danger',
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
        </div>
    )
}
