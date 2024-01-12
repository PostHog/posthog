import { actions, kea, path, reducers } from 'kea'

import type { globalModalsLogicType } from './GlobalModalsType'

export const globalModalsLogic = kea<globalModalsLogicType>([
    path(['layout', 'navigation', 'globalModalsLogic']),
    actions({
        showCreateOrganizationModal: true,
        hideCreateOrganizationModal: true,
        showCreateProjectModal: true,
        hideCreateProjectModal: true,
    }),
    reducers({
        isCreateOrganizationModalShown: [
            false,
            {
                showCreateOrganizationModal: () => true,
                hideCreateOrganizationModal: () => false,
            },
        ],
        isCreateProjectModalShown: [
            false,
            {
                showCreateProjectModal: () => true,
                hideCreateProjectModal: () => false,
            },
        ],
    }),
])
