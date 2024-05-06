import { LemonButton } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { actionLogic } from 'scenes/actions/actionLogic'
import { PluginImage } from 'scenes/plugins/plugin/PluginImage'
import { urls } from 'scenes/urls'

export function ActionPlugins(): JSX.Element | null {
    const { action } = useValues(actionLogic)

    if (!action?.plugin_configs?.length) {
        return null
    }

    return (
        <>
            <h2 className="subtitle">Connected apps</h2>

            {action.plugin_configs.map((pluginConfig) => (
                <div key={pluginConfig.id} className="flex items-center gap-2 border rounded bg-bg-light p-2">
                    <PluginImage plugin={pluginConfig.plugin_info} size="small" />
                    <span className="font-semibold">{pluginConfig.plugin_info.name}</span>
                    <span className="flex-1" />

                    <LemonButton type="secondary" size="small" to={urls.projectApp(pluginConfig.id)}>
                        Configure
                    </LemonButton>
                </div>
            ))}
        </>
    )
}
