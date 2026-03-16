import { kea, path, selectors } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { organizationLogic } from 'scenes/organizationLogic'

import type { interProjectCopyLogicType } from './interProjectCopyLogicType'

export const interProjectCopyLogic = kea<interProjectCopyLogicType>([
    path(['scenes', 'resource-transfer', 'interProjectCopyLogic']),

    selectors({
        canCopyToProject: [
            () => [organizationLogic.selectors.currentOrganization, featureFlagLogic.selectors.featureFlags],
            (currentOrganization, featureFlags): boolean => {
                const hasMultipleProjects = (currentOrganization?.teams?.length ?? 0) > 1
                const interProjectTransfersEnabled = !!featureFlags[FEATURE_FLAGS.INTER_PROJECT_TRANSFERS]
                return hasMultipleProjects && interProjectTransfersEnabled
            },
        ],
    }),
])
