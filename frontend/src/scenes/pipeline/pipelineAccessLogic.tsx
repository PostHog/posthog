import { connect, kea, path, selectors } from 'kea'

import { userLogic } from 'scenes/userLogic'

import { canConfigurePlugins, canGloballyManagePlugins } from './access'
import type { pipelineAccessLogicType } from './pipelineAccessLogicType'

export const pipelineAccessLogic = kea<pipelineAccessLogicType>([
    path(['scenes', 'pipeline', 'pipelineAccessLogic']),
    connect(() => ({
        values: [userLogic, ['user']],
    })),
    selectors({
        // This is currently an organization level setting but might in the future be user level
        // it's better to add the permission checks everywhere now
        canGloballyManagePlugins: [(s) => [s.user], (user) => canGloballyManagePlugins(user?.organization)],
        canConfigurePlugins: [(s) => [s.user], (user) => canConfigurePlugins(user?.organization)],
    }),
])
