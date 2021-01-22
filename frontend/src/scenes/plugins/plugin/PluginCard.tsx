import { Button, Card, Col, Popconfirm, Row, Switch, Tag } from 'antd'
import { useActions, useValues } from 'kea'
import React from 'react'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { PluginConfigType, PluginErrorType } from '~/types'
import {
    CheckOutlined,
    CloudDownloadOutlined,
    LoadingOutlined,
    PlusOutlined,
    SettingOutlined,
    SyncOutlined,
    WarningOutlined,
} from '@ant-design/icons'
import { Link } from 'lib/components/Link'
import { PluginImage } from './PluginImage'
import { PluginError } from './PluginError'
import { LocalPluginTag } from './LocalPluginTag'
import { PluginInstallationType, PluginUpgradeType } from 'scenes/plugins/types'
import { SourcePluginTag } from './SourcePluginTag'
import { CommunityPluginTag } from './CommunityPluginTag'

interface PluginCardProps {
    name: string
    description?: string
    url?: string
    pluginConfig?: PluginConfigType
    upgrades?: PluginUpgradeType
    pluginType?: PluginInstallationType
    pluginId?: number
    error?: PluginErrorType
    maintainer?: string
    showUpdateButton?: boolean
}

export function PluginCard({
    name,
    description,
    url,
    pluginType,
    pluginConfig,
    upgrades,
    pluginId,
    error,
    maintainer,
    showUpdateButton,
}: PluginCardProps): JSX.Element {
    const { editPlugin, toggleEnabled, installPlugin, resetPluginConfigError } = useActions(pluginsLogic)
    const { loading, installingPluginUrl, checkingForUpdates } = useValues(pluginsLogic)

    const canConfigure = pluginId && !pluginConfig?.global
    const switchDisabled = pluginConfig?.global

    return (
        <Col
            style={{ width: '100%', marginBottom: 20 }}
            data-attr={`plugin-card-${pluginConfig ? 'installed' : 'available'}`}
        >
            <Card className="plugin-card">
                <Row align="middle" className="plugin-card-row">
                    {pluginConfig && (
                        <Col>
                            <Popconfirm
                                placement="topLeft"
                                title={`Are you sure you wish to ${
                                    pluginConfig.enabled ? 'disable' : 'enable'
                                } this plugin?`}
                                onConfirm={() =>
                                    pluginConfig.id
                                        ? toggleEnabled({ id: pluginConfig.id, enabled: !pluginConfig.enabled })
                                        : editPlugin(pluginId || null, { __enabled: true })
                                }
                                okText="Yes"
                                cancelText="No"
                                disabled={switchDisabled}
                            >
                                <div>
                                    <Switch checked={pluginConfig.enabled} disabled={switchDisabled} />
                                </div>
                            </Popconfirm>
                        </Col>
                    )}
                    <Col className={pluginConfig ? 'hide-plugin-image-below-500' : ''}>
                        <PluginImage pluginType={pluginType} url={url} />
                    </Col>
                    <Col style={{ flex: 1 }}>
                        <div>
                            <strong style={{ marginRight: 8 }}>{name}</strong>
                            {maintainer && !pluginId && <CommunityPluginTag isCommunity={maintainer === 'community'} />}
                            {!description && !url ? <br /> : null}
                            {pluginConfig?.error ? (
                                <PluginError
                                    error={pluginConfig.error}
                                    reset={() => resetPluginConfigError(pluginConfig?.id || 0)}
                                />
                            ) : error ? (
                                <PluginError error={error} />
                            ) : null}
                            {url?.startsWith('file:') ? <LocalPluginTag url={url} title="Local" /> : null}

                            {upgrades?.error ? (
                                <Tag color="red">
                                    <WarningOutlined /> Error checking for updates
                                </Tag>
                            ) : upgrades?.currentTag !== upgrades?.nextTag ? (
                                <Tag color="volcano">
                                    <CloudDownloadOutlined /> Update available!
                                </Tag>
                            ) : upgrades?.currentTag && upgrades.currentTag === upgrades.nextTag ? (
                                <Tag color="green">
                                    <CheckOutlined /> Up To Date
                                </Tag>
                            ) : checkingForUpdates && pluginType !== PluginInstallationType.Source ? (
                                <Tag color="blue">
                                    <LoadingOutlined /> Checking...
                                </Tag>
                            ) : null}

                            {pluginType === PluginInstallationType.Source ? <SourcePluginTag /> : null}
                        </div>
                        <div>
                            {description}
                            {url && (
                                <span>
                                    {description ? ' ' : ''}
                                    <Link
                                        to={url}
                                        target="_blank"
                                        rel="noopener noreferrer"
                                        style={{ whiteSpace: 'nowrap' }}
                                    >
                                        Learn more
                                    </Link>
                                    .
                                </span>
                            )}
                        </div>
                    </Col>
                    <Col>
                        {showUpdateButton ? (
                            <Button
                                type="primary"
                                className="padding-under-500"
                                onClick={() => editPlugin(pluginId || null)}
                            >
                                <span className="show-over-500">Update</span>
                                <span className="hide-over-500">
                                    <SyncOutlined />
                                </span>
                            </Button>
                        ) : canConfigure ? (
                            <Button
                                type="primary"
                                className="padding-under-500"
                                onClick={() => editPlugin(pluginId || null)}
                            >
                                <span className="show-over-500">Configure</span>
                                <span className="hide-over-500">
                                    <SettingOutlined />
                                </span>
                            </Button>
                        ) : !pluginId ? (
                            <Button
                                type="primary"
                                className="padding-under-500"
                                loading={loading && installingPluginUrl === url}
                                disabled={loading && installingPluginUrl !== url}
                                onClick={url ? () => installPlugin(url, PluginInstallationType.Repository) : undefined}
                                icon={<PlusOutlined />}
                            >
                                <span className="show-over-500">Install</span>
                            </Button>
                        ) : null}
                    </Col>
                </Row>
            </Card>
        </Col>
    )
}
