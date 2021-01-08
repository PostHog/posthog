import { Button, Card, Col, Popconfirm, Skeleton, Switch } from 'antd'
import { useActions, useValues } from 'kea'
import React from 'react'
import { pluginsLogic } from './pluginsLogic'
import { someParentMatchesSelector } from 'lib/utils'
import { PluginConfigType, PluginErrorType } from '~/types'
import { PlusOutlined } from '@ant-design/icons'
import { Link } from 'lib/components/Link'
import { PluginImage } from './PluginImage'
import { PluginError } from 'scenes/plugins/PluginError'
import { LocalPluginTag } from 'scenes/plugins/LocalPluginTag'
import { PluginInstallationType } from 'scenes/plugins/types'
import { SourcePluginTag } from 'scenes/plugins/SourcePluginTag'

interface PluginCardProps {
    name: string
    description?: string
    url?: string
    pluginConfig?: PluginConfigType
    pluginType?: PluginInstallationType
    pluginId?: number
    error?: PluginErrorType
}

export function PluginCard({
    name,
    description,
    url,
    pluginType,
    pluginConfig,
    pluginId,
    error,
}: PluginCardProps): JSX.Element {
    const { editPlugin, toggleEnabled, installPlugin, resetPluginConfigError } = useActions(pluginsLogic)
    const { loading } = useValues(pluginsLogic)

    const canConfigure = pluginId && !pluginConfig?.global
    const handleClick = (e: React.MouseEvent<HTMLDivElement, MouseEvent>): void => {
        if (someParentMatchesSelector(e.target as HTMLElement, '.ant-popover,.ant-tag')) {
            return
        }
        if (canConfigure) {
            editPlugin(pluginId || null)
        }
    }

    const switchDisabled = (pluginConfig && pluginConfig.global) || !pluginConfig || !pluginConfig.id

    return (
        <Col
            sm={12}
            md={12}
            lg={8}
            xl={6}
            style={{ cursor: pluginConfig && canConfigure ? 'pointer' : 'inherit', width: '100%', marginBottom: 20 }}
            onClick={handleClick}
            data-attr={`plugin-card-${pluginConfig ? 'installed' : 'available'}`}
        >
            <Card
                style={{ height: '100%', display: 'flex', marginBottom: 20 }}
                bodyStyle={{ display: 'flex', flexDirection: 'column', flexGrow: 1 }}
            >
                {pluginType === 'source' ? (
                    <SourcePluginTag style={{ position: 'absolute', top: 10, left: 10, cursor: 'pointer' }} />
                ) : null}
                {url?.startsWith('file:') ? (
                    <LocalPluginTag
                        url={url}
                        title="Local"
                        style={{ position: 'absolute', top: 10, left: 10, cursor: 'pointer' }}
                    />
                ) : null}
                {pluginConfig?.error ? (
                    <PluginError
                        error={pluginConfig.error}
                        reset={() => resetPluginConfigError(pluginConfig?.id || 0)}
                    />
                ) : error ? (
                    <PluginError error={error} />
                ) : null}
                <PluginImage pluginType={pluginType} url={url} />
                <div className="text-center mb" style={{ marginBottom: 16 }}>
                    <b>{name}</b>
                </div>
                <div style={{ flexGrow: 1, paddingBottom: 16 }}>{description}</div>
                <div style={{ display: 'flex', minHeight: 44, alignItems: 'center' }}>
                    <div
                        style={{ flexGrow: 1, display: 'flex', alignItems: 'center' }}
                        onClick={(e) => {
                            if (!switchDisabled) {
                                e.stopPropagation()
                            }
                        }}
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
                        )}
                        {!pluginConfig && url && (
                            <>
                                <Link to={url} target="_blank" rel="noopener noreferrer">
                                    Learn more
                                </Link>
                            </>
                        )}
                    </div>
                    <div>
                        {canConfigure && <Button type="primary">Configure</Button>}
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
                    </div>
                </div>
            </Card>
        </Col>
    )
}

export function PluginLoading(): JSX.Element {
    return (
        <>
            {[1, 2, 3].map((i) => {
                return (
                    <Col sm={12} md={12} lg={8} xl={6} key={i} style={{ marginBottom: 20 }}>
                        <Card>
                            <div className="text-center">
                                <Skeleton.Image />
                            </div>

                            <Skeleton paragraph={{ rows: 4 }} active />
                        </Card>
                    </Col>
                )
            })}
        </>
    )
}
