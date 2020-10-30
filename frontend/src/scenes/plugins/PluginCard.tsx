import { Col, Card, Button, Switch, Popconfirm, Skeleton } from 'antd'
import { useActions } from 'kea'
import React from 'react'
import { pluginsLogic } from './pluginsLogic'
import { ellipsis } from 'lib/utils'
import { PluginConfigType } from '~/types'
import { PlusOutlined } from '@ant-design/icons'
import { Link } from 'lib/components/Link'
import { PluginImage } from './PluginImage'

interface PluginCardType {
    name: string
    description: string
    url: string
    pluginConfig?: PluginConfigType
    pluginId?: number
}

export function PluginCard({ name, description, url, pluginConfig, pluginId }: PluginCardType): JSX.Element {
    const { editPlugin, toggleEnabled, installPlugin } = useActions(pluginsLogic)

    const handleClick = (): void => {
        if (pluginId) {
            editPlugin(pluginId)
        }
    }

    return (
        <Col
            sm={6}
            style={pluginConfig && { cursor: 'pointer' }}
            onClick={handleClick}
            data-attr={`plugin-card-${pluginConfig ? 'installed' : 'available'}`}
        >
            <Card
                style={{ height: '100%', display: 'flex' }}
                bodyStyle={{ display: 'flex', flexDirection: 'column', flexGrow: 1 }}
            >
                <PluginImage url={url} />
                <div className="text-center oh-spaced-bottom">
                    <b>{name}</b>
                </div>
                <div style={{ flexGrow: 1, paddingBottom: 16 }}>{ellipsis(description, 180)}</div>
                <div style={{ display: 'flex' }}>
                    <div
                        style={{ flexGrow: 1, display: 'flex', alignItems: 'center' }}
                        onClick={(e) => e.stopPropagation()}
                    >
                        {pluginConfig && (
                            <Popconfirm
                                placement="topLeft"
                                title={`Are you sure you wish to ${
                                    pluginConfig.enabled ? 'disable' : 'enable'
                                } this plugin?`}
                                onConfirm={() => toggleEnabled({ id: pluginConfig.id, enabled: !pluginConfig.enabled })}
                                okText="Yes"
                                cancelText="No"
                            >
                                <div>
                                    <Switch checked={pluginConfig.enabled} />
                                    {pluginConfig.global && (
                                        <div style={{ paddingTop: 4, fontSize: 11 }} className="text-muted">
                                            Globally enabled
                                        </div>
                                    )}
                                </div>
                            </Popconfirm>
                        )}
                        {!pluginConfig && (
                            <>
                                <Link to={url} target="_blank" rel="noopener noreferrer">
                                    Learn more
                                </Link>
                            </>
                        )}
                    </div>
                    <div>
                        {pluginId && <Button type="primary">Configure</Button>}
                        {!pluginId && (
                            <Button type="primary" onClick={() => installPlugin(url)} icon={<PlusOutlined />}>
                                Install
                            </Button>
                        )}
                    </div>
                </div>
            </Card>
        </Col>
    )
}

export function PluginLoading(): JSX.Element {
    return (
        <>
            {[1, 2, 3, 4].map((i) => {
                return (
                    <Col sm={6} key={i}>
                        <Card>
                            <div className="text-center">
                                <Skeleton.Image />
                            </div>

                            <Skeleton paragraph={{ rows: 6 }} active />
                        </Card>
                    </Col>
                )
            })}
        </>
    )
}
