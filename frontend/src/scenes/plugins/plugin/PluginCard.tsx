import { Button, Card, Col, Popconfirm, Row, Switch, Tag } from 'antd'
import { useActions, useValues } from 'kea'
import React from 'react'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { PluginConfigType, PluginErrorType } from '~/types'
import {
    CheckOutlined,
    CloudDownloadOutlined,
    LoadingOutlined,
    SettingOutlined,
    WarningOutlined,
    DownOutlined,
} from '@ant-design/icons'
import { Link } from 'lib/components/Link'
import { PluginImage } from './PluginImage'
import { PluginError } from './PluginError'
import { LocalPluginTag } from './LocalPluginTag'
import { PluginInstallationType, PluginTypeWithConfig } from 'scenes/plugins/types'
import { SourcePluginTag } from './SourcePluginTag'
import { CommunityPluginTag } from './CommunityPluginTag'
import { UpdateAvailable } from 'scenes/plugins/plugin/UpdateAvailable'
import { userLogic } from 'scenes/userLogic'

interface PluginCardProps {
    plugin: Partial<PluginTypeWithConfig>
    pluginConfig?: PluginConfigType
    error?: PluginErrorType
    maintainer?: string
    showUpdateButton?: boolean
    order?: number
    maxOrder?: number
    rearranging?: boolean
    DragColumn?: React.ComponentClass | React.FC
}

export function PluginCard({
    plugin,
    error,
    maintainer,
    showUpdateButton,
    order,
    maxOrder,
    rearranging,
    DragColumn = ({ children }) => <Col className="order-handle">{children}</Col>,
}: PluginCardProps): JSX.Element {
    const {
        name,
        description,
        url,
        plugin_type: pluginType,
        pluginConfig,
        tag,
        latest_tag: latestTag,
        id: pluginId,
        updateStatus,
        hasMoved,
    } = plugin

    const { editPlugin, toggleEnabled, installPlugin, resetPluginConfigError, updatePlugin, rearrange } = useActions(
        pluginsLogic
    )
    const { loading, installingPluginUrl, checkingForUpdates, updatingPlugin } = useValues(pluginsLogic)
    const { user } = useValues(userLogic)

    const canInstall = user?.plugin_access.install
    const canConfigure = pluginId
    const switchDisabled = rearranging

    return (
        <Col
            style={{ width: '100%', marginBottom: 20 }}
            className={`plugins-scene-plugin-card-col${rearranging ? ` rearranging` : ''}`}
            data-attr={`plugin-card-${pluginConfig ? 'installed' : 'available'}`}
        >
            <Card className="plugins-scene-plugin-card">
                <Row align="middle" className="plugin-card-row">
                    {typeof order === 'number' && typeof maxOrder === 'number' ? (
                        <DragColumn>
                            <div className={`arrow${order !== maxOrder ? ' hide' : ''}`}>
                                <DownOutlined />
                            </div>
                            <div>
                                <Tag color={hasMoved ? '#bd0225' : '#555'} onClick={rearrange}>
                                    {order}
                                </Tag>
                            </div>
                            <div className={`arrow${order === maxOrder ? ' hide' : ''}`}>
                                <DownOutlined />
                            </div>
                        </DragColumn>
                    ) : null}
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

                            {canInstall ? (
                                <>
                                    {url?.startsWith('file:') ? <LocalPluginTag url={url} title="Local" /> : null}
                                    {updateStatus?.error ? (
                                        <Tag color="red">
                                            <WarningOutlined /> Error checking for updates
                                        </Tag>
                                    ) : checkingForUpdates &&
                                      !updateStatus &&
                                      pluginType !== PluginInstallationType.Source ? (
                                        <Tag color="blue">
                                            <LoadingOutlined /> Checking for updates…
                                        </Tag>
                                    ) : url && latestTag && tag ? (
                                        tag === latestTag ? (
                                            <Tag color="green">
                                                <CheckOutlined /> Up to date
                                            </Tag>
                                        ) : (
                                            <UpdateAvailable url={url} tag={tag} latestTag={latestTag} />
                                        )
                                    ) : null}
                                    {pluginType === PluginInstallationType.Source ? <SourcePluginTag /> : null}
                                </>
                            ) : null}
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
                        {showUpdateButton && pluginId ? (
                            <Button
                                type={updateStatus?.updated ? 'default' : 'primary'}
                                className="padding-under-500"
                                onClick={() => (updateStatus?.updated ? editPlugin(pluginId) : updatePlugin(pluginId))}
                                loading={!!updatingPlugin}
                                icon={updateStatus?.updated ? <CheckOutlined /> : <CloudDownloadOutlined />}
                            >
                                <span className="show-over-500">{updateStatus?.updated ? 'Updated' : 'Update'}</span>
                            </Button>
                        ) : canConfigure && pluginId ? (
                            <Button
                                type="primary"
                                className="padding-under-500"
                                disabled={rearranging}
                                onClick={() => editPlugin(pluginId)}
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
                                icon={<CloudDownloadOutlined />}
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
