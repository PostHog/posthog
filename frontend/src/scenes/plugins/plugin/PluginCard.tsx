import { Button, Card, Col, Popconfirm, Row, Space, Switch, Tag, Tooltip } from 'antd'
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
    LineChartOutlined,
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
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'

export function PluginAboutButton({ url, disabled = false }: { url: string; disabled?: boolean }): JSX.Element {
    return (
        <Space>
            <Tooltip title="About">
                <LinkButton to={url} target="_blank" rel="noopener noreferrer" disabled={disabled}>
                    <InfoCircleOutlined />
                </LinkButton>
            </Tooltip>
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
    unorderedPlugin?: boolean
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
    unorderedPlugin = false,
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

    const {
        editPlugin,
        toggleEnabled,
        installPlugin,
        resetPluginConfigError,
        rearrange,
        showPluginLogs,
        showPluginMetrics,
    } = useActions(pluginsLogic)
    const { loading, installingPluginUrl, checkingForUpdates, pluginUrlToMaintainer } = useValues(pluginsLogic)
    const { user } = useValues(userLogic)

    const { featureFlags } = useValues(featureFlagLogic)

    const hasSpecifiedMaintainer = maintainer || (plugin.url && pluginUrlToMaintainer[plugin.url])
    const pluginMaintainer = maintainer || pluginUrlToMaintainer[plugin.url || '']

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
                    {unorderedPlugin ? (
                        <Tooltip title="This plugin does not do any processing in order." placement="topRight">
                            <Col>
                                <Tag color="#555">-</Tag>
                            </Col>
                        </Tooltip>
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
                                <Switch checked={pluginConfig.enabled ?? false} disabled={rearranging} />
                            </Popconfirm>
                        </Col>
                    )}
                    <Col className={pluginConfig ? 'hide-plugin-image-below-500' : ''}>
                        <PluginImage pluginType={pluginType} url={url} />
                    </Col>
                    <Col style={{ flex: 1 }}>
                        <div>
                            <strong style={{ marginRight: 8 }}>{name}</strong>
                            {hasSpecifiedMaintainer && (
                                <CommunityPluginTag isCommunity={pluginMaintainer === 'community'} />
                            )}
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
                            {url && <PluginAboutButton url={url} disabled={rearranging} />}
                            {showUpdateButton && pluginId ? (
                                <PluginUpdateButton
                                    updateStatus={updateStatus}
                                    pluginId={pluginId}
                                    rearranging={rearranging}
                                />
                            ) : pluginId ? (
                                <>
                                    {featureFlags[FEATURE_FLAGS.PLUGIN_METRICS] &&
                                    Object.keys(plugin.metrics || {}).length > 0 ? (
                                        <Space>
                                            <Tooltip title="Metrics">
                                                <Button onClick={() => showPluginMetrics(pluginId)}>
                                                    <LineChartOutlined />
                                                </Button>
                                            </Tooltip>
                                        </Space>
                                    ) : null}
                                    <Tooltip
                                        title={
                                            pluginConfig?.id
                                                ? 'Logs'
                                                : 'Logs – enable the plugin for the first time to view them'
                                        }
                                    >
                                        <Button
                                            className="padding-under-500"
                                            disabled={rearranging || !pluginConfig?.id}
                                            onClick={() => showPluginLogs(pluginId)}
                                            data-attr="plugin-logs"
                                        >
                                            <UnorderedListOutlined />
                                        </Button>
                                    </Tooltip>
                                    <Tooltip title="Configure">
                                        <Button
                                            type="primary"
                                            className="padding-under-500"
                                            disabled={rearranging}
                                            onClick={() => editPlugin(pluginId)}
                                            data-attr="plugin-configure"
                                        >
                                            <SettingOutlined />
                                        </Button>
                                    </Tooltip>
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
