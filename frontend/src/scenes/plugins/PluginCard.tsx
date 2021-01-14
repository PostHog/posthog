import { Button, Card, Col, Popconfirm, Row, Skeleton, Switch } from 'antd'
import { useActions, useValues } from 'kea'
import React from 'react'
import { pluginsLogic } from './pluginsLogic'
import { PluginConfigType, PluginErrorType } from '~/types'
import { PlusOutlined } from '@ant-design/icons'
import { Link } from 'lib/components/Link'
import { PluginImage } from './PluginImage'
import { PluginError } from 'scenes/plugins/PluginError'
import { LocalPluginTag } from 'scenes/plugins/LocalPluginTag'
import { PluginInstallationType } from 'scenes/plugins/types'
import { SourcePluginTag } from 'scenes/plugins/SourcePluginTag'
import { CommunityPluginTag } from './CommunityPluginTag'

interface PluginCardProps {
    name: string
    description?: string
    url?: string
    pluginConfig?: PluginConfigType
    pluginType?: PluginInstallationType
    pluginId?: number
    error?: PluginErrorType
    maintainer: string
}

export function PluginCard({
    name,
    description,
    url,
    pluginType,
    pluginConfig,
    pluginId,
    error,
    maintainer,
}: PluginCardProps): JSX.Element {
    const { editPlugin, toggleEnabled, installPlugin, resetPluginConfigError } = useActions(pluginsLogic)
    const { loading } = useValues(pluginsLogic)

    const canConfigure = pluginId && !pluginConfig?.global
    const switchDisabled = (pluginConfig && pluginConfig.global) || !pluginConfig || !pluginConfig.id

    return (
        <Col
            style={{ width: '100%', marginBottom: 20 }}
            data-attr={`plugin-card-${pluginConfig ? 'installed' : 'available'}`}
        >
            <Card
                style={{ height: '100%', display: 'flex' }}
                bodyStyle={{ display: 'flex', flexDirection: 'column', flexGrow: 1, padding: 15 }}
            >
                <Row style={{ alignItems: 'center' }}>
                    {pluginConfig && (
                        <Col style={{ marginRight: 14 }}>
                            <Popconfirm
                                placement="topLeft"
                                title={`Are you sure you wish to ${
                                    pluginConfig.enabled ? 'disable' : 'enable'
                                } this plugin?`}
                                onConfirm={() => toggleEnabled({ id: pluginConfig.id, enabled: !pluginConfig.enabled })}
                                okText="Yes"
                                cancelText="No"
                                disabled={switchDisabled}
                            >
                                <div>
                                    <Switch checked={pluginConfig.enabled} disabled={switchDisabled} />
                                    {pluginConfig.global && (
                                        <span style={{ marginLeft: 10, fontSize: 11 }} className="text-muted">
                                            Globally enabled
                                        </span>
                                    )}
                                </div>
                            </Popconfirm>
                        </Col>
                    )}
                    <Col style={{ marginRight: 14 }}>
                        <PluginImage pluginType={pluginType} url={url} />
                    </Col>
                    <Col style={{ marginRight: 14, flex: 1 }}>
                        <div>
                            {pluginConfig?.error ? (
                                <PluginError
                                    error={pluginConfig.error}
                                    reset={() => resetPluginConfigError(pluginConfig?.id || 0)}
                                />
                            ) : error ? (
                                <PluginError error={error} />
                            ) : null}
                            <b>{name}</b>
                            {url?.startsWith('file:') ? (
                                <LocalPluginTag url={url} title="Local" style={{ marginLeft: 10 }} />
                            ) : null}
                            {!pluginId && <CommunityPluginTag isCommunity={maintainer === 'community'} />}
                            {!pluginConfig && url && (
                                <Link to={url} target="_blank" rel="noopener noreferrer" style={{ marginLeft: 10 }}>
                                    Learn more
                                </Link>
                            )}
                        </div>
                        <div>
                            {pluginType === 'source' ? <SourcePluginTag style={{ marginRight: 10 }} /> : null}

                            {description}
                        </div>
                    </Col>
                    <Col>
                        {canConfigure && (
                            <Button type="primary" onClick={() => editPlugin(pluginId || null)}>
                                Configure
                            </Button>
                        )}
                        {!pluginId && (
                            <Button
                                type="primary"
                                loading={loading}
                                onClick={url ? () => installPlugin(url, PluginInstallationType.Repository) : undefined}
                                icon={<PlusOutlined />}
                            >
                                Install
                            </Button>
                        )}
                    </Col>
                </Row>
            </Card>
        </Col>
    )
}

export function PluginLoading(): JSX.Element {
    return (
        <>
            {[1, 2, 3].map((i) => (
                <Col key={i} style={{ marginBottom: 20, width: '100%' }}>
                    <Card>
                        <Row style={{ alignItems: 'center' }}>
                            <Col style={{ marginRight: 14, width: 30 }}>
                                <Skeleton title paragraph={false} active />
                            </Col>
                            <Col style={{ marginRight: 14 }}>
                                <Skeleton.Image style={{ width: 60, height: 60 }} />
                            </Col>
                            <Col style={{ marginRight: 14, flex: 1 }}>
                                <Skeleton title={false} paragraph={{ rows: 2 }} active />
                            </Col>
                            <Col style={{ marginRight: 14 }}>
                                <Skeleton.Button style={{ width: 100 }} />
                            </Col>
                        </Row>
                    </Card>
                </Col>
            ))}
        </>
    )
}
