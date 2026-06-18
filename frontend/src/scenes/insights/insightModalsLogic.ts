import { actions, connect, kea, key, listeners, path, props, reducers } from 'kea'

import { InsightLogicProps } from '~/types'

import { insightLogic } from './insightLogic'
import type { insightModalsLogicType } from './insightModalsLogicType'
import { keyForInsightLogicProps } from './sharedUtils'

export const insightModalsLogic = kea<insightModalsLogicType>([
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps('new')),
    path((key) => ['scenes', 'insights', 'insightModalsLogic', key]),

    connect((props: InsightLogicProps) => ({
        actions: [insightLogic(props), ['saveInsightSuccess', 'saveInsightFailure']],
    })),

    actions({
        openAddToDashboardModal: true,
        closeAddToDashboardModal: true,
        // Defer opening the add-to-dashboard modal until the in-flight save completes. Opening it concurrently with a
        // save races the save response (which carries the pre-modal `dashboards` list) against the dashboard the user
        // picks, silently overwriting that addition. Setting the flag and opening on `saveInsightSuccess` serializes them.
        openAddToDashboardModalAfterSave: true,
        openTerraformModal: true,
        closeTerraformModal: true,
    }),

    reducers({
        isAddToDashboardModalOpen: [
            false,
            {
                openAddToDashboardModal: () => true,
                closeAddToDashboardModal: () => false,
            },
        ],
        pendingAddToDashboardAfterSave: [
            false,
            {
                openAddToDashboardModalAfterSave: () => true,
                openAddToDashboardModal: () => false,
                closeAddToDashboardModal: () => false,
                saveInsightFailure: () => false,
            },
        ],
        isTerraformModalOpen: [
            false,
            {
                openTerraformModal: () => true,
                closeTerraformModal: () => false,
            },
        ],
    }),

    listeners(({ actions, values }) => ({
        saveInsightSuccess: () => {
            if (values.pendingAddToDashboardAfterSave) {
                actions.openAddToDashboardModal()
            }
        },
    })),
])
