import { afterMount, kea, key, path, props } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import type { Experiment } from '~/types'

import type { featureFlagRelatedExperimentsLogicType } from './featureFlagRelatedExperimentsLogicType'

export interface FeatureFlagRelatedExperimentsLogicProps {
    featureFlagId: number
}

export const featureFlagRelatedExperimentsLogic = kea<featureFlagRelatedExperimentsLogicType>([
    path(['scenes', 'experiments', 'featureFlagRelatedExperimentsLogic']),
    props({} as FeatureFlagRelatedExperimentsLogicProps),
    key((props) => props.featureFlagId),
    loaders(({ props }) => ({
        relatedExperiments: [
            [] as Experiment[],
            {
                loadRelatedExperiments: async () => {
                    const response = await api.get(
                        `api/projects/@current/experiments/?feature_flag_id=${props.featureFlagId}`
                    )
                    return response.results || []
                },
            },
        ],
    })),
    afterMount(({ actions }) => {
        actions.loadRelatedExperiments()
    }),
])
