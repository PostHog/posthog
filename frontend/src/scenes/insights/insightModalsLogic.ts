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
        actions: [insightLogic(props), ['saveInsight', 'saveInsightSuccess', 'saveInsightFailure']],
    })),

    actions({
        openAddToDashboardModal: true,
        closeAddToDashboardModal: true,
        saveAndAddToDashboard: true,
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
                saveAndAddToDashboard: () => true,
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
        // Save first, then open the add-to-dashboard modal once the save lands. Opening it concurrently with the save
        // races the save response (which carries the pre-modal `dashboards` list) against the dashboard the user picks,
        // silently overwriting that addition. `pendingAddToDashboardAfterSave` carries the intent across the save, and
        // reducers run before listeners, so the flag must NOT be cleared on `saveInsightSuccess` itself — it is read
        // here and cleared by `openAddToDashboardModal`.
        saveAndAddToDashboard: () => {
            actions.saveInsight(false)
        },
        saveInsightSuccess: () => {
            if (values.pendingAddToDashboardAfterSave) {
                actions.openAddToDashboardModal()
            }
        },
    })),
])
