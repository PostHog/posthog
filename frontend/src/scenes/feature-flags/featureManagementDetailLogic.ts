import { connect, kea, path, props } from 'kea'
import { teamLogic } from 'scenes/teamLogic'

import type { featureManagementDetailLogicType } from './featureManagementDetailLogicType'
import { featureManagementLogic } from './featureManagementLogic'

export const featureManagementDetailLogic = kea<featureManagementDetailLogicType>([
    props({}),
    path(['scenes', 'features', 'featureManagementDetailLogic']),
    connect({
        values: [teamLogic, ['currentTeamId'], featureManagementLogic, ['activeFeatureId', 'activeFeature']],
    }),
])
