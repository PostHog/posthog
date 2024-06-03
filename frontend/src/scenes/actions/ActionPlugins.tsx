import { IconPlus } from '@posthog/icons'
import { LemonButton, LemonSkeleton, LemonTable } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { useEffect } from 'react'
import { actionLogic } from 'scenes/actions/actionLogic'
import { PluginImage } from 'scenes/plugins/plugin/PluginImage'
import { urls } from 'scenes/urls'

import { EntityFilter, PipelineNodeTab, PipelineStage } from '~/types'

export function ActionPlugins(): JSX.Element | null {
    const { action, matchingPluginConfigs, matchingPluginConfigsLoading } = useValues(actionLogic)
    const { loadMatchingPluginConfigs } = useActions(actionLogic)

    const pluginFilters = !!useFeatureFlag('PLUGINS_FILTERING')

    useEffect(() => {
        loadMatchingPluginConfigs()
    }, [])

    if (!pluginFilters && !matchingPluginConfigs?.length) {
        return null
    }

    const actionFilter: EntityFilter = {
        id: `${action?.id}`,
        name: action?.name,
        type: 'actions',
    }

    const newDestinationUrl =
        urls.pipelineNodeNew(PipelineStage.Destination) +
        `#configuration=${JSON.stringify({
            name: `${action?.name} webhook`,
            filters: {
                actions: [actionFilter],
            },
        })}`

    return (
        <>
            <div className="flex items-start">
                <div className="flex-1">
                    <h2 className="subtitle">Connected data pipelines</h2>
                    <p>Actions can act as filters for data pipelines such as Webhooks or Slack notifications.</p>
                </div>
                <LemonButton icon={<IconPlus />} type="primary" to={newDestinationUrl}>
                    Create destination
                </LemonButton>
            </div>

            {matchingPluginConfigsLoading ? (
                <div className="space-y-px">
                    <LemonSkeleton className="w-1/2 h-6" repeat={3} />
                </div>
            ) : (
                <LemonTable
                    dataSource={matchingPluginConfigs ?? []}
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
                    emptyState={<>No connected pipelines</>}
                />
            )}
        </>
    )
}
