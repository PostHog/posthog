import { actions, kea, path, reducers } from 'kea'

import { ExperimentTemplate } from './constants'
import type { experimentTemplateModalLogicType } from './experimentTemplateModalLogicType'

export const experimentTemplateModalLogic = kea<experimentTemplateModalLogicType>([
    path(['scenes', 'experiments', 'ExperimentForm', 'ExperimentTemplates', 'experimentTemplateModalLogic']),

    actions({
        openTemplateModal: (template: ExperimentTemplate) => ({ template }),
        closeTemplateModal: true,
    }),

    reducers({
        isModalOpen: [
            false,
            {
                openTemplateModal: () => true,
                closeTemplateModal: () => false,
            },
        ],
        template: [
            null as ExperimentTemplate | null,
            {
                openTemplateModal: (_, { template }) => template,
                closeTemplateModal: () => null,
            },
        ],
    }),
])
