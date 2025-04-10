import { connect, kea, path, selectors } from 'kea'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature } from '~/types'

import { canConfigurePlugins, canGloballyManagePlugins } from './access'
import type { pipelineAccessLogicType } from './pipelineAccessLogicType'
import { Destination, NewDestinationItemType, SiteApp, Transformation } from './types'

export const pipelineAccessLogic = kea<pipelineAccessLogicType>([
    path(['scenes', 'pipeline', 'pipelineAccessLogic']),
    connect(() => ({
        values: [userLogic, ['user', 'hasAvailableFeature']],
    })),
    selectors({
        // This is currently an organization level setting but might in the future be user level
        // it's better to add the permission checks everywhere now
        canGloballyManagePlugins: [(s) => [s.user], (user) => canGloballyManagePlugins(user?.organization)],
        canConfigurePlugins: [(s) => [s.user], (user) => canConfigurePlugins(user?.organization)],
        canEnableNewDestinations: [
            (s) => [s.user, s.hasAvailableFeature],
            (user, hasAvailableFeature) =>
                canConfigurePlugins(user?.organization) && hasAvailableFeature(AvailableFeature.DATA_PIPELINES),
        ],

        canEnableDestination: [
            (s) => [s.canEnableNewDestinations],
            (
                canEnableNewDestinations
            ): ((destination: Destination | NewDestinationItemType | SiteApp | Transformation) => boolean) => {
                return (destination: Destination | NewDestinationItemType | SiteApp | Transformation) => {
                    return 'free' in destination
                        ? destination.free || canEnableNewDestinations
                        : canEnableNewDestinations
                }
            },
        ],
    }),
])
