import { connect, kea, path } from 'kea'
import { teamLogic } from 'scenes/teamLogic'

import { DESTINATION_TYPES } from './hog-functions-list/constants'
import { hogFunctionsListLogic } from './hog-functions-list/hogFunctionsListLogic'
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
            hogFunctionsListLogic({ types: DESTINATION_TYPES }),
            ['loading as destinationsLoading', 'destinations'],
        ],
        actions: [
            pipelineTransformationsLogic,
            ['loadPlugins as loadTransformationPlugins', 'loadPluginConfigs as loadTransformationPluginConfigs'],
            hogFunctionsListLogic({ types: DESTINATION_TYPES }),
            [
                'loadPlugins as loadDestinationPlugins',
                'loadPluginConfigs as loadDestinationPluginConfigs',
                'loadBatchExports as loadBatchExportConfigs',
            ],
        ],
    }),
])
