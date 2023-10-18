import { LemonButton, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { IconCheckmark, IconCloudDownload } from 'lib/lemon-ui/icons'
import { PluginImage } from 'scenes/plugins/plugin/PluginImage'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { PluginTypeWithConfig, PluginRepositoryEntry, PluginInstallationType } from 'scenes/plugins/types'
import { PluginType } from '~/types'
import { PluginTags } from './components'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { Popconfirm } from 'antd'
import { DeleteOutlined, GlobalOutlined, RollbackOutlined } from '@ant-design/icons'
import { canGloballyManagePlugins } from 'scenes/plugins/access'
import { userLogic } from 'scenes/userLogic'

export function AppManagementView({
    plugin,
}: {
    plugin: PluginTypeWithConfig | PluginType | PluginRepositoryEntry
}): JSX.Element {
    const { user } = useValues(userLogic)

    if (!canGloballyManagePlugins(user?.organization)) {
        return <></>
    }
    const { installingPluginUrl, pluginsNeedingUpdates, pluginsUpdating, loading, unusedPlugins } =
        useValues(pluginsLogic)
    const { installPlugin, editPlugin, updatePlugin, uninstallPlugin, patchPlugin } = useActions(pluginsLogic)

    return (
        <div className="flex justify-between items-center">
            <div className="flex items-center gap-4">
                <PluginImage plugin={plugin} />
                <div>
                    <div className="flex gap-2 items-center">
                        <span className="font-semibold truncate">
                            <Link to={plugin.url} target={'blank'}>
                                {plugin.name}
                            </Link>
                        </span>
                        <PluginTags plugin={plugin} />
                    </div>
                    <div className="text-sm">{plugin.description}</div>
                </div>
            </div>

            <div className="flex gap-2 whitespace-nowrap items-center justify-end">
                {'id' in plugin ? (
                    <>
                        {'updateStatus' in plugin && pluginsNeedingUpdates.find((x) => x.id === plugin.id) && (
                            <LemonButton
                                type="secondary"
                                size="small"
                                onClick={() => {
                                    plugin.updateStatus?.updated ? editPlugin(plugin.id) : updatePlugin(plugin.id)
                                }}
                                loading={pluginsUpdating.includes(plugin.id)}
                                icon={plugin.updateStatus?.updated ? <IconCheckmark /> : <IconCloudDownload />}
                            >
                                {plugin.updateStatus?.updated ? 'Updated' : 'Update'}
                            </LemonButton>
                        )}
                        <Popconfirm
                            placement="topLeft"
                            title="Are you sure you wish to uninstall this app completely?"
                            onConfirm={() => uninstallPlugin(plugin.id)}
                            okText="Uninstall"
                            cancelText="Cancel"
                            className="Plugins__Popconfirm"
                        >
                            <LemonButton
                                type="primary"
                                status="danger"
                                size="small"
                                icon={<DeleteOutlined />}
                                disabledReason={
                                    unusedPlugins.includes(plugin.id) ? undefined : 'This app is still in use.'
                                }
                                data-attr="plugin-uninstall"
                            >
                                Uninstall
                            </LemonButton>
                        </Popconfirm>
                        {plugin.is_global ? (
                            <Tooltip
                                title={
                                    <>
                                        This app can currently be used by other organizations in this instance of
                                        PostHog. This action will <b>disable and hide it</b> for all organizations other
                                        than yours.
                                    </>
                                }
                            >
                                <LemonButton
                                    type="secondary"
                                    size="small"
                                    icon={<RollbackOutlined />}
                                    onClick={() => patchPlugin(plugin.id, { is_global: false })}
                                >
                                    Make local
                                </LemonButton>
                            </Tooltip>
                        ) : (
                            <Tooltip
                                title={
                                    <>
                                        This action will mark this app as installed for <b>all organizations</b> in this
                                        instance of PostHog.
                                    </>
                                }
                            >
                                <LemonButton
                                    type="secondary"
                                    size="small"
                                    icon={<GlobalOutlined />}
                                    onClick={() => patchPlugin(plugin.id, { is_global: true })}
                                >
                                    Make global
                                </LemonButton>
                            </Tooltip>
                        )}
                    </>
                ) : (
                    <LemonButton
                        type="primary"
                        loading={loading && installingPluginUrl === plugin.url}
                        icon={<IconCloudDownload />}
                        size="small"
                        onClick={() =>
                            plugin.url ? installPlugin(plugin.url, PluginInstallationType.Repository) : undefined
                        }
                    >
                        Install
                    </LemonButton>
                )}
            </div>
        </div>
    )
}
