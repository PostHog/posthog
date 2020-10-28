import { Col, Card, Button, Switch } from 'antd'
import { useActions } from 'kea'
import React from 'react'
import { pluginsLogic } from './pluginsLogic'
import { PluginTypeWithConfig } from './types'
import imgPluginDefault from 'public/plugin-default.svg'
import { ellipsis } from 'lib/utils'

export function PluginCard({ plugin }: { plugin: PluginTypeWithConfig }): JSX.Element {
    const { editPlugin } = useActions(pluginsLogic)
    return (
        <Col sm={6}>
            <Card
                style={{ height: '100%', display: 'flex' }}
                bodyStyle={{ display: 'flex', flexDirection: 'column', flexGrow: 1 }}
            >
                <Card
                    className="card-elevated"
                    style={{
                        width: 60,
                        height: 60,
                        marginBottom: 24,
                        display: 'flex',
                        justifyContent: 'center',
                        alignItems: 'center',
                        marginLeft: 'auto',
                        marginRight: 'auto',
                    }}
                >
                    <img src={imgPluginDefault} alt="" />
                </Card>
                <div className="text-center oh-spaced-bottom">
                    <b>{plugin.name}</b>
                </div>
                <div style={{ flexGrow: 1, paddingBottom: 16 }}>{ellipsis(plugin.description, 180)}</div>
                <div style={{ display: 'flex' }}>
                    <div style={{ flexGrow: 1 }}>
                        <Switch checked={plugin.pluginConfig?.enabled} />
                        {plugin.pluginConfig?.global && (
                            <div style={{ paddingTop: 4 }} className="text-extra-small text-muted">
                                Globally enabled
                            </div>
                        )}
                    </div>
                    <div>
                        <Button type="primary" onClick={() => editPlugin(plugin.id)}>
                            Configure
                        </Button>
                    </div>
                </div>
            </Card>
        </Col>
    )
}
