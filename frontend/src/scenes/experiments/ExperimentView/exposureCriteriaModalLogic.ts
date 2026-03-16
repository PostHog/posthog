import { actions, kea, path, reducers } from 'kea'

import type { ExperimentExposureCriteria } from '~/queries/schema/schema-general'
import { NEW_EXPERIMENT } from '~/scenes/experiments/constants'

import type { exposureCriteriaModalLogicType } from './exposureCriteriaModalLogicType'

export const exposureCriteriaModalLogic = kea<exposureCriteriaModalLogicType>([
    path(['scenes', 'experiments', 'ExperimentForm', 'exposureCriteriaModalLogic']),

    actions({
        openExposureCriteriaModal: (exposureCriteria?: ExperimentExposureCriteria) => ({ exposureCriteria }),
        closeExposureCriteriaModal: true,
        setExposureCriteria: (exposureCriteria: ExperimentExposureCriteria) => ({ exposureCriteria }),
    }),

    reducers({
        isExposureCriteriaModalOpen: [
            false,
            {
                openExposureCriteriaModal: () => true,
                closeExposureCriteriaModal: () => false,
            },
        ],
        exposureCriteria: [
            NEW_EXPERIMENT.exposure_criteria as ExperimentExposureCriteria,
            {
                openExposureCriteriaModal: (_, { exposureCriteria }) =>
                    (exposureCriteria ?? NEW_EXPERIMENT.exposure_criteria) as ExperimentExposureCriteria,
                closeExposureCriteriaModal: () => NEW_EXPERIMENT.exposure_criteria as ExperimentExposureCriteria,
                setExposureCriteria: (_, { exposureCriteria }) => exposureCriteria,
            },
        ],
    }),
])
