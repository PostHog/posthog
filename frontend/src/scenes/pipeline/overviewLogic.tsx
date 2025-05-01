import { connect, kea, path } from 'kea'
import { teamLogic } from 'scenes/teamLogic'

import { DESTINATION_TYPES } from './destinations/constants'
import { pipelineDestinationsLogic } from './destinations/destinationsLogic'
import type { pipelineOverviewLogicType } from './overviewLogicType'
import { pipelineTransformationsLogic } from './transformationsLogic'

export const pipelineOverviewLogic = kea<pipelineOverviewLogicType>([
    path(['scenes', 'pipeline', 'overviewLogic']),
    connect(() => ({
        values: [
            teamLogic,
            ['currentTeamId'],
            pipelineTransformationsLogic,
            ['loading as transformationsLoading', 'transformations'],
            pipelineDestinationsLogic({ types: DESTINATION_TYPES }),
            ['loading as destinationsLoading', 'destinations'],
        ],
        actions: [
            pipelineTransformationsLogic,
            ['loadPlugins as loadTransformationPlugins', 'loadPluginConfigs as loadTransformationPluginConfigs'],
            pipelineDestinationsLogic({ types: DESTINATION_TYPES }),
            [
                'loadPlugins as loadDestinationPlugins',
                'loadPluginConfigs as loadDestinationPluginConfigs',
                'loadBatchExports as loadBatchExportConfigs',
            ],
        ],
    })),
])
