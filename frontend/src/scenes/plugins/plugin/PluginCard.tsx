import { Button, Card, Col, Popconfirm, Row, Space, Switch, Tag } from 'antd'
import { useActions, useValues } from 'kea'
import React from 'react'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { PluginConfigType, PluginErrorType } from '~/types'
import {
    CheckOutlined,
    CloudDownloadOutlined,
    LoadingOutlined,
    UnorderedListOutlined,
    SettingOutlined,
    WarningOutlined,
    InfoCircleOutlined,
    DownOutlined,
    GlobalOutlined,
} from '@ant-design/icons'
import { PluginImage } from './PluginImage'
import { PluginError } from './PluginError'
import { LocalPluginTag } from './LocalPluginTag'
import { PluginInstallationType, PluginTypeWithConfig } from 'scenes/plugins/types'
import { SourcePluginTag } from './SourcePluginTag'
import { CommunityPluginTag } from './CommunityPluginTag'
import { UpdateAvailable } from 'scenes/plugins/plugin/UpdateAvailable'
import { userLogic } from 'scenes/userLogic'
import { endWithPunctation } from '../../../lib/utils'
import { canInstallPlugins } from '../access'
import { LinkButton } from 'lib/components/LinkButton'
import { PluginUpdateButton } from './PluginUpdateButton'

export function ExtraPluginButtons({ url, disabled = false }: { url: string; disabled?: boolean }): JSX.Element {
    return (
        <Space>
            <LinkButton to={url} target="_blank" rel="noopener noreferrer" disabled={disabled}>
                <InfoCircleOutlined />
                <span className="show-over-500">About</span>
            </LinkButton>
        </Space>
    )
}

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
        is_global,
        organization_id,
        organization_name,
    } = plugin

    const { editPlugin, toggleEnabled, installPlugin, resetPluginConfigError, rearrange, showPluginLogs } = useActions(
        pluginsLogic
    )
    const { loading, installingPluginUrl, checkingForUpdates } = useValues(pluginsLogic)
    const { user } = useValues(userLogic)

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
                            <div className={`arrow${order === 1 ? ' hide' : ''}`}>
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
                                disabled={rearranging}
                            >
                                <Switch
                                    checked={pluginConfig.enabled ?? false}
                                    onClick={() => console.log(pluginConfig.enabled)}
                                    disabled={rearranging}
                                />
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
                            {pluginConfig?.error ? (
                                <PluginError
                                    error={pluginConfig.error}
                                    reset={() => resetPluginConfigError(pluginConfig?.id || 0)}
                                />
                            ) : error ? (
                                <PluginError error={error} />
                            ) : null}
                            {is_global && (
                                <Tag color="blue">
                                    <GlobalOutlined /> Managed by {organization_name}
                                </Tag>
                            )}
                            {canInstallPlugins(user?.organization, organization_id) && (
                                <>
                                    {url?.startsWith('file:') ? <LocalPluginTag url={url} title="Local" /> : null}
                                    {updateStatus?.error ? (
                                        <Tag color="red">
                                            <WarningOutlined /> Error checking for updates
                                        </Tag>
                                    ) : checkingForUpdates &&
                                      !updateStatus &&
                                      pluginType !== PluginInstallationType.Source &&
                                      !url?.startsWith('file:') ? (
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
                            )}
                        </div>
                        <div>{endWithPunctation(description)}</div>
                    </Col>
                    <Col>
                        <Space>
                            {url && <ExtraPluginButtons url={url} disabled={rearranging} />}
                            {showUpdateButton && pluginId ? (
                                <PluginUpdateButton
                                    updateStatus={updateStatus}
                                    pluginId={pluginId}
                                    rearranging={rearranging}
                                />
                            ) : pluginId ? (
                                <>
                                    <Button
                                        className="padding-under-500"
                                        disabled={rearranging}
                                        onClick={() => showPluginLogs(pluginId)}
                                        data-attr="plugin-logs"
                                    >
                                        <UnorderedListOutlined />
                                        <span className="show-over-500">Logs</span>
                                    </Button>
                                    <Button
                                        type="primary"
                                        className="padding-under-500"
                                        disabled={rearranging}
                                        onClick={() => editPlugin(pluginId)}
                                        data-attr="plugin-configure"
                                    >
                                        <SettingOutlined />
                                        <span className="show-over-500">Configure</span>
                                    </Button>
                                </>
                            ) : !pluginId ? (
                                <Button
                                    type="primary"
                                    className="padding-under-500"
                                    loading={loading && installingPluginUrl === url}
                                    disabled={loading && installingPluginUrl !== url}
                                    onClick={
                                        url ? () => installPlugin(url, PluginInstallationType.Repository) : undefined
                                    }
                                    icon={<CloudDownloadOutlined />}
                                    data-attr="plugin-install"
                                >
                                    <span className="show-over-500">Install</span>
                                </Button>
                            ) : null}
                        </Space>
                    </Col>
                </Row>
            </Card>
        </Col>
    )
}
