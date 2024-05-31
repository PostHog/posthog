import { LemonButton, LemonTable } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { useEffect } from 'react'
import { actionLogic } from 'scenes/actions/actionLogic'
import { PluginImage } from 'scenes/plugins/plugin/PluginImage'
import { urls } from 'scenes/urls'

import { PipelineNodeTab, PipelineStage } from '~/types'

export function ActionPlugins(): JSX.Element | null {
    const { matchingPluginConfigs } = useValues(actionLogic)
    const { loadMatchingPluginConfigs } = useActions(actionLogic)

    useEffect(() => {
        loadMatchingPluginConfigs()
    }, [])

    if (!matchingPluginConfigs?.length) {
        return null
    }

    return (
        <>
            <h2 className="subtitle">Connected data pipelines</h2>

            <LemonTable
                dataSource={matchingPluginConfigs}
                columns={[
                    {
                        title: 'Data pipeline',
                        render: (_, config) => (
                            <div className="flex items-center gap-2">
                                <PluginImage plugin={config.plugin_info} size="small" />
                                <LemonTableLink
                                    title={config.name ?? config.plugin_info.name}
                                    to={urls.pipelineNode(
                                        PipelineStage.Destination,
                                        config.id,
                                        PipelineNodeTab.Configuration
                                    )}
                                />
                            </div>
                        ),
                    },
                    {
                        title: '',
                        width: 0,
                        render: (_, config) => (
                            <LemonButton
                                type="secondary"
                                size="small"
                                to={urls.pipelineNode(
                                    PipelineStage.Destination,
                                    config.id,
                                    PipelineNodeTab.Configuration
                                )}
                            >
                                Configure
                            </LemonButton>
                        ),
                    },
                ]}
            />
        </>
    )
}
