import React, { useEffect, useState } from 'react'
import { useActions, useValues } from 'kea'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { Button, Row } from 'antd'
import { ArrowDownOutlined, GlobalOutlined, DatabaseOutlined } from '@ant-design/icons'
import { Drawer } from 'lib/components/Drawer'
import { Responsive, WidthProvider } from 'react-grid-layout'

const ReactGridLayout = WidthProvider(Responsive)

export function PluginsOrderDrawer(): JSX.Element {
    const { installedPlugins, reorderingPlugins } = useValues(pluginsLogic)
    const { stopReorderingPlugins } = useActions(pluginsLogic)

    const [orderAffected, setOrderAffected] = useState(false)
    const [newConfigIdsOrder, setNewConfigIdsOrder] = useState<number[]>(
        installedPlugins.map((plugin) => plugin.pluginConfig.id)
    )
    console.log(newConfigIdsOrder)
    useEffect(() => {
        setNewConfigIdsOrder(installedPlugins.map((plugin) => plugin.pluginConfig.id))
    }, [installedPlugins])

    return (
        <Drawer
            visible={!!reorderingPlugins}
            onClose={stopReorderingPlugins}
            width="min(90vw, 420px)"
            title="Reordering Plugins"
            footer={
                <Row justify="end">
                    <Button onClick={stopReorderingPlugins} style={{ marginRight: 16 }}>
                        Cancel
                    </Button>
                    <Button type="primary" disabled={!orderAffected}>
                        Save
                    </Button>
                </Row>
            }
        >
            <p>Event {orderAffected ? 'will be' : 'are'} processed by plugins in this order.</p>
            <p>
                This matters because the pipeline is consecutive and each plugin after the entry point processes the
                result of its predecessor's processing. Any plugin can also reject an event altogether, in which case
                later plugins won't know it ever was received.
            </p>
            <Button icon={<GlobalOutlined />} style={{ textAlign: 'left', width: '100%' }} type="primary">
                Raw event received
            </Button>
            <ReactGridLayout
                style={{ position: 'relative' }}
                useCSSTransforms={false}
                isDraggable
                isResizable={false}
                breakpoints={{ any: 9999 }}
                layouts={{
                    any: installedPlugins.map((plugin, index) => ({
                        i: String(plugin.id),
                        x: 0,
                        y: index,
                        w: 1,
                        h: 1,
                    })),
                }}
                cols={{ any: 1 }}
                rowHeight={32}
                margin={[0, 16]}
                containerPadding={[0, 16]}
                onLayoutChange={(layout) => {
                    setOrderAffected(true)
                    setNewConfigIdsOrder(layout.sort((a, b) => a.y - b.y).map((row) => Number(row.i)))
                }}
            >
                {installedPlugins.map((plugin) => (
                    <Button icon={<ArrowDownOutlined />} style={{ textAlign: 'left' }} key={String(plugin.id)}>
                        {plugin.name}
                    </Button>
                ))}
            </ReactGridLayout>
            <Button icon={<DatabaseOutlined />} style={{ textAlign: 'left', width: '100%' }} type="primary">
                Processed event ingested
            </Button>
        </Drawer>
    )
}
