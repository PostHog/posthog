import { connect, kea, path, selectors } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature } from '~/types'

import { canConfigurePlugins, canGloballyManagePlugins } from './access'
import type { pipelineAccessLogicType } from './pipelineAccessLogicType'
import { Destination, NewDestinationItemType, SiteApp, Transformation } from './types'

export const pipelineAccessLogic = kea<pipelineAccessLogicType>([
    path(['scenes', 'pipeline', 'pipelineAccessLogic']),
    connect(() => ({
        values: [userLogic, ['user', 'hasAvailableFeature'], featureFlagLogic, ['featureFlags']],
    })),
    selectors({
        // This is currently an organization level setting but might in the future be user level
        // it's better to add the permission checks everywhere now
        canGloballyManagePlugins: [(s) => [s.user], (user) => canGloballyManagePlugins(user?.organization)],
        canConfigurePlugins: [(s) => [s.user], (user) => canConfigurePlugins(user?.organization)],
        canEnableNewDestinations: [
            (s) => [s.user, s.hasAvailableFeature, s.featureFlags],
            (user, hasAvailableFeature, featureFlags) =>
                canConfigurePlugins(user?.organization) &&
                (hasAvailableFeature(AvailableFeature.DATA_PIPELINES) || !!featureFlags[FEATURE_FLAGS.CDP_NEW_PRICING]),
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
