import { actions, kea, path, reducers } from 'kea'

import type { ExperimentExposureCriteria } from '~/queries/schema/schema-general'

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
            null as ExperimentExposureCriteria | null,
            {
                openExposureCriteriaModal: (_, { exposureCriteria }) => exposureCriteria ?? null,
                closeExposureCriteriaModal: () => null,
                setExposureCriteria: (_, { exposureCriteria }) => exposureCriteria,
            },
        ],
    }),
])
