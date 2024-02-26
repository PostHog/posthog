import { IconGear } from '@posthog/icons'
import { LemonBadge, LemonButton, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { IconEllipsis, IconErrorOutline, IconLegend, IconLink } from 'lib/lemon-ui/icons'
import { LemonMenu, LemonMenuItem } from 'lib/lemon-ui/LemonMenu'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { PLUGINS_ALLOWED_WITHOUT_DATA_PIPELINES } from 'scenes/pipeline/utils'
import { PluginImage } from 'scenes/plugins/plugin/PluginImage'
import { SuccessRateBadge } from 'scenes/plugins/plugin/SuccessRateBadge'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { PluginRepositoryEntry, PluginTypeWithConfig } from 'scenes/plugins/types'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature, PluginType } from '~/types'

import { PluginTags } from './components'

export function AppView({
    plugin,
}: {
    plugin: PluginTypeWithConfig | PluginType | PluginRepositoryEntry
}): JSX.Element {
    const { showAppMetricsForPlugin, sortableEnabledPlugins } = useValues(pluginsLogic)
    const { editPlugin, toggleEnabled, openReorderModal } = useActions(pluginsLogic)
    const { hasAvailableFeature } = useValues(userLogic)

    const pluginConfig = 'pluginConfig' in plugin ? plugin.pluginConfig : null
    const isConfigured = !!pluginConfig?.id

    // If pluginConfig is enabled always show it regardless of the feature availability
    // So self-hosted users who were using the plugins in the past can continue to use them
    if (!hasAvailableFeature(AvailableFeature.DATA_PIPELINES) && !pluginConfig?.enabled) {
        // If the app isn't in the allowed apps list don't show it
        if (!plugin.url || !PLUGINS_ALLOWED_WITHOUT_DATA_PIPELINES.has(plugin.url)) {
            return <></>
        }
    }

    const orderedIndex = sortableEnabledPlugins.indexOf(plugin as unknown as any) + 1
    const menuItems: LemonMenuItem[] = []

    if (plugin.url) {
        menuItems.push({
            label: 'Source',
            sideIcon: <IconLink />,
            to: plugin.url,
            targetBlank: true,
        })
    }

    if (isConfigured) {
        menuItems.push({
            label: pluginConfig?.enabled ? 'Disable' : 'Enable',
            status: pluginConfig.enabled ? 'danger' : 'default',
            onClick: () =>
                toggleEnabled({
                    id: pluginConfig.id,
                    enabled: !pluginConfig.enabled,
                }),
        })
    }

    return (
        <div className="flex justify-between items-center">
            <div className="flex items-center gap-4">
                {isConfigured && pluginConfig.enabled && (
                    <span>
                        <Tooltip
                            title={
                                <>
                                    {orderedIndex ? (
                                        <>
                                            Apps that react to incoming events run in order. This app runs in position{' '}
                                            {orderedIndex}.
                                            <br />
                                            Click to change the order of the plugins.
                                        </>
                                    ) : (
                                        <>As this app is not part of the processing flow, the order is unimportant </>
                                    )}
                                </>
                            }
                        >
                            <LemonButton onClick={openReorderModal} noPadding>
                                {orderedIndex ? (
                                    <LemonBadge.Number status="primary" count={orderedIndex} maxDigits={3} />
                                ) : (
                                    <LemonBadge status="primary" content="-" />
                                )}
                            </LemonButton>
                        </Tooltip>
                    </span>
                )}
                <PluginImage plugin={plugin} />
                <div>
                    <div className="flex gap-2 items-center">
                        {pluginConfig && showAppMetricsForPlugin(plugin) && pluginConfig.id && (
                            <SuccessRateBadge
                                deliveryRate={pluginConfig.delivery_rate_24h ?? null}
                                pluginConfigId={pluginConfig.id}
                            />
                        )}
                        <span className="font-semibold truncate">
                            {isConfigured ? (
                                <Link
                                    to={isConfigured ? urls.appMetrics(pluginConfig.id || '') : plugin.url}
                                    target={!isConfigured ? 'blank' : undefined}
                                >
                                    {plugin.name}
                                </Link>
                            ) : (
                                plugin.name
                            )}
                        </span>
                        <PluginTags plugin={plugin} />
                    </div>
                    <div className="text-sm">{plugin.description}</div>
                </div>
            </div>

            <div className="flex gap-2 whitespace-nowrap items-center justify-end">
                {'id' in plugin && (
                    <>
                        {pluginConfig && !pluginConfig.enabled && isConfigured && (
                            <LemonButton
                                type="secondary"
                                size="small"
                                onClick={() =>
                                    toggleEnabled({
                                        id: pluginConfig.id,
                                        enabled: true,
                                    })
                                }
                            >
                                Enable
                            </LemonButton>
                        )}

                        {pluginConfig &&
                            pluginConfig.id &&
                            (pluginConfig.error ? (
                                <LemonButton
                                    type="secondary"
                                    status="danger"
                                    size="small"
                                    icon={<IconErrorOutline />}
                                    to={urls.appLogs(pluginConfig.id)}
                                >
                                    Errors
                                </LemonButton>
                            ) : (
                                <LemonButton
                                    type="secondary"
                                    size="small"
                                    icon={<IconLegend />}
                                    to={urls.appLogs(pluginConfig.id)}
                                >
                                    Logs & metrics
                                </LemonButton>
                            ))}

                        <LemonButton
                            type="primary"
                            size="small"
                            icon={<IconGear />}
                            onClick={() => editPlugin(plugin.id)}
                        >
                            Configure
                        </LemonButton>
                    </>
                )}

                <LemonMenu items={menuItems} placement="bottom-end">
                    <LemonButton size="small" icon={<IconEllipsis />} />
                </LemonMenu>
            </div>
        </div>
    )
}
