import { afterMount, connect, kea, path, selectors } from 'kea'
import { teamLogic } from 'scenes/teamLogic'

import { pipelineDestinationsLogic } from './destinationsLogic'
import type { pipelineOverviewLogicType } from './overviewLogicType'
import { pipelineTransformationsLogic } from './transformationsLogic'

export const pipelineOverviewLogic = kea<pipelineOverviewLogicType>([
    path(['scenes', 'pipeline', 'overviewLogic']),
    connect({
        values: [
            teamLogic,
            ['currentTeamId'],
            pipelineTransformationsLogic,
            [
                'pluginsLoading as transformationPluginsLoading',
                'pluginConfigsLoading as transformationPluginConfigsLoading',
                'displayablePluginConfigs as transformations',
            ],
            pipelineDestinationsLogic,
            [
                'pluginsLoading as destinationPluginsLoading',
                'pluginConfigsLoading as destinationPluginConfigsLoading',
                'batchExportConfigsLoading',
                'destinations',
            ],
        ],
        actions: [
            pipelineTransformationsLogic,
            ['loadPlugins as loadTransformationPlugins', 'loadPluginConfigs as loadTransformationPluginConfigs'],
            pipelineDestinationsLogic,
            [
                'loadPlugins as loadDestinationPlugins',
                'loadPluginConfigs as loadDestinationPluginConfigs',
                'loadBatchExports as loadBatchExportConfigs',
            ],
        ],
    }),
    selectors({
        transformationsLoading: [
            (s) => [s.transformationPluginsLoading, s.transformationPluginConfigsLoading],
            (transformationPluginsLoading, transformationPluginConfigsLoading) =>
                transformationPluginsLoading || transformationPluginConfigsLoading,
        ],
        destinationsLoading: [
            (s) => [s.destinationPluginsLoading, s.destinationPluginConfigsLoading, s.batchExportConfigsLoading],
            (pluginsLoading, destinationPluginConfigsLoading, batchExportConfigsLoading) =>
                pluginsLoading || destinationPluginConfigsLoading || batchExportConfigsLoading,
        ],
    }),
    afterMount(({ actions }) => {
        // transformations
        actions.loadTransformationPlugins()
        actions.loadTransformationPluginConfigs()

        // destinations
        actions.loadDestinationPlugins()
        actions.loadDestinationPluginConfigs()
        actions.loadBatchExportConfigs()
    }),
])
