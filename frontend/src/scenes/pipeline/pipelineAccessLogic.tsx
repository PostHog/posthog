import { connect, kea, path, selectors } from 'kea'
import { canConfigurePlugins, canGloballyManagePlugins } from 'scenes/plugins/access'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature } from '~/types'

import type { pipelineAccessLogicType } from './pipelineAccessLogicType'

export const pipelineAccessLogic = kea<pipelineAccessLogicType>([
    path(['scenes', 'pipeline', 'pipelineAccessLogic']),
    connect({
        values: [userLogic, ['user', 'hasAvailableFeature']],
    }),
    selectors({
        // This is currently an organization level setting but might in the future be user level
        // it's better to add the permission checks everywhere now
        canGloballyManagePlugins: [(s) => [s.user], (user) => canGloballyManagePlugins(user?.organization)],
        canConfigurePlugins: [(s) => [s.user], (user) => canConfigurePlugins(user?.organization)],
        canEnableNewDestinations: [
            (s) => [s.user, s.hasAvailableFeature],
            (user, hasAvailableFeature) =>
                user?.is_impersonated ||
                (canConfigurePlugins(user?.organization) && hasAvailableFeature(AvailableFeature.DATA_PIPELINES)),
        ],
    }),
])
