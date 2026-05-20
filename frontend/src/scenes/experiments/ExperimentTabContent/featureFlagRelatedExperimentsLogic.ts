import { afterMount, connect, kea, key, path, props } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'

import type { Experiment } from '~/types'

import type { featureFlagRelatedExperimentsLogicType } from './featureFlagRelatedExperimentsLogicType'

export interface FeatureFlagRelatedExperimentsLogicProps {
    featureFlagId: number
}

export const featureFlagRelatedExperimentsLogic = kea<featureFlagRelatedExperimentsLogicType>([
    path(['scenes', 'experiments', 'featureFlagRelatedExperimentsLogic']),
    props({} as FeatureFlagRelatedExperimentsLogicProps),
    key((props) => props.featureFlagId),
    connect(() => ({ values: [teamLogic, ['currentProjectId']] })),
    loaders(({ props, values }) => ({
        relatedExperiments: [
            [] as Experiment[],
            {
                loadRelatedExperiments: async () => {
                    const response = await api.get(
                        `api/projects/${values.currentProjectId}/experiments/?feature_flag_id=${props.featureFlagId}`
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
