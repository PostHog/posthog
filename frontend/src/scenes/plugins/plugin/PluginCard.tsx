import { Button, Tag } from 'antd'
import { useActions, useValues } from 'kea'
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
    ClockCircleOutlined,
    LineChartOutlined,
    UpOutlined,
} from '@ant-design/icons'
import { PluginImage } from './PluginImage'
import { PluginError } from './PluginError'
import { LocalPluginTag } from './LocalPluginTag'
import { PluginInstallationType, PluginTypeWithConfig } from 'scenes/plugins/types'
import { SourcePluginTag } from './SourcePluginTag'
import { UpdateAvailable } from 'scenes/plugins/plugin/UpdateAvailable'
import { userLogic } from 'scenes/userLogic'
import { endWithPunctation } from 'lib/utils'
import { canInstallPlugins } from '../access'
import { PluginUpdateButton } from './PluginUpdateButton'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { LemonSwitch, Link } from '@posthog/lemon-ui'
import { organizationLogic } from 'scenes/organizationLogic'
import { PluginsAccessLevel } from 'lib/constants'
import { urls } from 'scenes/urls'
import { SuccessRateBadge } from './SuccessRateBadge'
import clsx from 'clsx'
import { CommunityTag } from 'lib/CommunityTag'

export function PluginAboutButton({ url, disabled = false }: { url: string; disabled?: boolean }): JSX.Element {
    return (
        <Tooltip title="About">
            <Link to={url} target="_blank">
                <Button disabled={disabled}>
                    <InfoCircleOutlined />
                </Button>
            </Link>
        </Tooltip>
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
    DragColumn = ({ children }) => <div className="order-handle">{children}</div>,
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

    const { editPlugin, toggleEnabled, installPlugin, resetPluginConfigError, rearrange, showPluginLogs } =
        useActions(pluginsLogic)
    const { loading, installingPluginUrl, checkingForUpdates, pluginUrlToMaintainer, showAppMetricsForPlugin } =
        useValues(pluginsLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const { user } = useValues(userLogic)

    const hasSpecifiedMaintainer = maintainer || (plugin.url && pluginUrlToMaintainer[plugin.url])
    const pluginMaintainer = maintainer || pluginUrlToMaintainer[plugin.url || '']

    return (
        <div className="w-full mb-5" data-attr={`plugin-card-${pluginConfig ? 'installed' : 'available'}`}>
            <div className="border rounded p-4 bg-bg-light plugins-scene-plugin-card">
                <div className="flex space-x-3 items-center">
                    {typeof order === 'number' && typeof maxOrder === 'number' ? (
                        <DragColumn>
                            <div className={clsx('arrow', order === 1 && 'invisible')}>
                                <UpOutlined />
                            </div>
                            <div>
                                <Tag color={hasMoved ? '#bd0225' : '#555'} onClick={rearrange}>
                                    {order}
                                </Tag>
                            </div>
                            <div className={clsx('arrow', order === maxOrder && 'invisible')}>
                                <DownOutlined />
                            </div>
                        </DragColumn>
                    ) : null}
                    {unorderedPlugin ? (
                        <Tooltip title="This app does not do any processing in order." placement="topRight">
                            <Tag color="#555">-</Tag>
                        </Tooltip>
                    ) : null}
                    {pluginConfig &&
                        (pluginConfig.id ? (
                            <LemonSwitch
                                checked={pluginConfig.enabled ?? false}
                                disabled={rearranging}
                                onChange={() => toggleEnabled({ id: pluginConfig.id, enabled: !pluginConfig.enabled })}
                            />
                        ) : (
                            <Tooltip title="Please configure this plugin before enabling it">
                                <LemonSwitch checked={false} disabled={true} />
                            </Tooltip>
                        ))}
                    <div className={pluginConfig ? 'hide-plugin-image-below-500' : ''}>
                        <PluginImage plugin={plugin} />
                    </div>
                    <div className="flex flex-col flex-1">
                        <div className="flex items-center">
                            <strong className="flex items-center mr-2 gap-1">
                                {showAppMetricsForPlugin(plugin) && pluginConfig?.id && (
                                    <SuccessRateBadge
                                        deliveryRate={pluginConfig.delivery_rate_24h ?? null}
                                        pluginConfigId={pluginConfig.id}
                                    />
                                )}
                                {name}
                            </strong>
                            {hasSpecifiedMaintainer && <CommunityTag isCommunity={pluginMaintainer === 'community'} />}
                            {pluginConfig?.error ? (
                                <PluginError
                                    error={pluginConfig.error}
                                    reset={() => resetPluginConfigError(pluginConfig?.id || 0)}
                                />
                            ) : error ? (
                                <PluginError error={error} />
                            ) : null}
                            {is_global &&
                                !!currentOrganization &&
                                currentOrganization.plugins_access_level >= PluginsAccessLevel.Install && (
                                    <Tooltip title={`This plugin is managed by the ${organization_name} organization`}>
                                        <Tag color="blue" icon={<GlobalOutlined />}>
                                            Global
                                        </Tag>
                                    </Tooltip>
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
                    </div>
                    <div className="space-x-2">
                        {url && <PluginAboutButton url={url} disabled={rearranging} />}
                        {showUpdateButton && pluginId ? (
                            <PluginUpdateButton
                                updateStatus={updateStatus}
                                pluginId={pluginId}
                                rearranging={rearranging}
                            />
                        ) : pluginId ? (
                            <>
                                {showAppMetricsForPlugin(plugin) && pluginConfig?.id ? (
                                    <Tooltip title="App metrics">
                                        <Button
                                            className="padding-under-500"
                                            disabled={rearranging}
                                            data-attr="app-metrics"
                                        >
                                            <Link to={urls.appMetrics(pluginConfig.id)}>
                                                <LineChartOutlined />
                                            </Link>
                                        </Button>
                                    </Tooltip>
                                ) : null}
                                {pluginConfig?.id ? (
                                    <Tooltip title="Activity history">
                                        <Button
                                            className="padding-under-500"
                                            disabled={rearranging}
                                            data-attr="plugin-history"
                                        >
                                            <Link to={urls.appHistory(pluginConfig.id)}>
                                                <ClockCircleOutlined />
                                            </Link>
                                        </Button>
                                    </Tooltip>
                                ) : null}
                                <Tooltip
                                    title={
                                        pluginConfig?.id
                                            ? 'Logs'
                                            : 'Logs – enable the app for the first time to view them'
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
                                onClick={url ? () => installPlugin(url, PluginInstallationType.Repository) : undefined}
                                icon={<CloudDownloadOutlined />}
                                data-attr="plugin-install"
                            >
                                <span className="show-over-500">Install</span>
                            </Button>
                        ) : null}
                    </div>
                </div>
            </div>
        </div>
    )
}
