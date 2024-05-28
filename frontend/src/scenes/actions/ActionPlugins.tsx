import { LemonButton } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { actionLogic } from 'scenes/actions/actionLogic'
import { PluginImage } from 'scenes/plugins/plugin/PluginImage'
import { urls } from 'scenes/urls'

import { PipelineNodeTab, PipelineStage } from '~/types'

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
                    <LemonTableLink
                        title={pluginConfig.plugin_info.name}
                        to={urls.pipelineNode(
                            PipelineStage.Destination,
                            pluginConfig.id,
                            PipelineNodeTab.Configuration
                        )}
                    />
                    <span className="flex-1" />

                    <LemonButton
                        type="secondary"
                        size="small"
                        to={urls.pipelineNode(
                            PipelineStage.Destination,
                            pluginConfig.id,
                            PipelineNodeTab.Configuration
                        )}
                    >
                        Configure
                    </LemonButton>
                </div>
            ))}
        </>
    )
}
