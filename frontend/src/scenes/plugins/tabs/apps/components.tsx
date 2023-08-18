import { PluginType } from '~/types'
import { LemonTag } from '@posthog/lemon-ui'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { PluginRepositoryEntry } from 'scenes/plugins/types'
import { useValues } from 'kea'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'

export function RepositoryTag({ plugin }: { plugin: PluginType | PluginRepositoryEntry }): JSX.Element | null {
    const { pluginUrlToMaintainer } = useValues(pluginsLogic)

    const pluginMaintainer = plugin.maintainer || pluginUrlToMaintainer[plugin.url || '']
    const isOfficial = pluginMaintainer === 'official'

    if ('plugin_type' in plugin) {
        if (plugin.plugin_type === 'source') {
            return <LemonTag>Source code</LemonTag>
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
