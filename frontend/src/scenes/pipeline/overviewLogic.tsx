import { connect, kea, path } from 'kea'
import { teamLogic } from 'scenes/teamLogic'

import { pipelineDestinationsLogic } from './destinations/destinationsLogic'
import type { pipelineOverviewLogicType } from './overviewLogicType'
import { pipelineTransformationsLogic } from './transformationsLogic'

export const pipelineOverviewLogic = kea<pipelineOverviewLogicType>([
    path(['scenes', 'pipeline', 'overviewLogic']),
    connect({
        values: [
            teamLogic,
            ['currentTeamId'],
            pipelineTransformationsLogic,
            ['loading as transformationsLoading', 'transformations'],
            pipelineDestinationsLogic,
            ['loading as destinationsLoading', 'destinations'],
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
])
