import { createSetupDetectionLogic } from 'lib/components/ProductEmptyState/setupDetectionLogic'
import { projectLogic } from 'scenes/projectLogic'

import { ProductKey } from '~/queries/schema/schema-general'

import { cloudAgentsRunsList } from '../generated/api'

/** Cloud agents needs no install step, so a project is set up when it has one run or more. */
export const cloudAgentsSetupLogic = createSetupDetectionLogic({
    productKey: ProductKey.CLOUD_AGENTS,
    path: ['products', 'cloud_agents', 'frontend', 'emptyState', 'cloudAgentsSetupLogic'],
    detect: async () => {
        const projectId = projectLogic.findMounted()?.values.currentProjectId
        if (!projectId) {
            return null
        }
        const response = await cloudAgentsRunsList(String(projectId), { limit: 1 })
        return response.count > 0 ? 'has-data' : 'needs-setup'
    },
})
