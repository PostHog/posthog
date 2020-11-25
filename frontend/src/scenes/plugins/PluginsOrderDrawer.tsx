import React from 'react'
import { useActions, useValues } from 'kea'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { Button, Row } from 'antd'
import { Drawer } from 'lib/components/Drawer'

export function PluginsOrderDrawer(): JSX.Element {
    const { reorderingPlugins } = useValues(pluginsLogic)
    const { stopReorderingPlugins } = useActions(pluginsLogic)

    return (
        <Drawer
            forceRender={true}
            visible={!!reorderingPlugins}
            onClose={stopReorderingPlugins}
            width="min(90vw, 420px)"
            title="Reordering Plugins"
            footer={
                <Row justify="end">
                    <Button onClick={stopReorderingPlugins} style={{ marginRight: 16 }}>
                        Cancel
                    </Button>
                    <Button type="primary" loading={false} onClick={stopReorderingPlugins}>
                        Save
                    </Button>
                </Row>
            }
        >
            XXX
        </Drawer>
    )
}
