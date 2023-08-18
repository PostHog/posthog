import { PluginType } from '~/types'
import { LemonTag } from '@posthog/lemon-ui'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { PluginRepositoryEntry } from 'scenes/plugins/types'
import { useValues } from 'kea'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { PluginsAccessLevel } from 'lib/constants'
import { copyToClipboard } from 'lib/utils'

export function RepositoryTag({ plugin }: { plugin: PluginType | PluginRepositoryEntry }): JSX.Element | null {
    const { pluginUrlToMaintainer } = useValues(pluginsLogic)

    const pluginMaintainer = plugin.maintainer || pluginUrlToMaintainer[plugin.url || '']
    const isOfficial = pluginMaintainer === 'official'

    if ('plugin_type' in plugin) {
        if (plugin.plugin_type === 'source') {
            return <LemonTag>Source code</LemonTag>
        }

        if (plugin.plugin_type === 'local' && plugin.url) {
            return (
                <LemonTag type="completion" onClick={async () => await copyToClipboard(plugin.url?.substring(5) || '')}>
                    Installed Locally
                </LemonTag>
            )
        }
    }

    if (!pluginMaintainer) {
        return null
    }

    return (
        <Tooltip
            title={
                !isOfficial
                    ? `This app was built by a community member, not the PostHog team.`
                    : `This app was built by the PostHog team.`
            }
        >
            <LemonTag type={isOfficial ? 'primary' : 'highlight'}>{isOfficial ? 'Official' : 'Community'}</LemonTag>
        </Tooltip>
    )
}

export function PluginTags({ plugin }: { plugin: PluginType | PluginRepositoryEntry }): JSX.Element | null {
    const { currentOrganization } = useValues(organizationLogic)

    return (
        <>
            <RepositoryTag plugin={plugin} />

            {'is_global' in plugin &&
                plugin.is_global &&
                !!currentOrganization &&
                currentOrganization.plugins_access_level >= PluginsAccessLevel.Install && (
                    <Tooltip title={`This plugin is managed by the ${plugin.organization_name} organization`}>
                        <LemonTag type="success">Global</LemonTag>
                    </Tooltip>
                )}
        </>
    )
}
