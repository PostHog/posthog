import api, { type CountedPaginatedResponse } from 'lib/api'
import { createSetupDetectionLogic } from 'lib/components/ProductEmptyState/setupDetectionLogic'
import { projectLogic } from 'scenes/projectLogic'

import { ProductKey } from '~/queries/schema/schema-general'

import { hogFunctionsList } from '../generated/api'

/**
 * Setup detection for the destinations empty state. Destinations are creation-first, so
 * "set up" means the project has at least one thing the scene would list: a destination
 * hog function, a legacy plugin destination, or a batch export. Counting only hog functions
 * would tell a project still exporting through plugins or batch exports to create its
 * first destination and hide the ones delivering its data today.
 */
export const destinationsSetupLogic = createSetupDetectionLogic({
    productKey: ProductKey.PIPELINE_DESTINATIONS,
    path: ['products', 'cdp', 'frontend', 'emptyState', 'destinationsSetupLogic'],
    detect: async () => {
        const projectId = String(projectLogic.findMounted()?.values.currentProjectId)
        const [hogFunctions, pluginDestinations, batchExports] = await Promise.all([
            hogFunctionsList(projectId, {
                type: ['destination', 'site_destination', 'internal_destination'],
                limit: 1,
            }),
            // The legacy plugin config endpoints are not in the OpenAPI spec, so there is
            // no generated client to call here.
            // nosemgrep: prefer-codegen-api
            api.get<CountedPaginatedResponse<unknown>>(
                `api/projects/${projectId}/pipeline_destination_configs/?limit=1`
            ),
            api.batchExports.list({ limit: 1 }),
        ])
        const total = hogFunctions.count + (pluginDestinations.count ?? 0) + (batchExports.count ?? 0)
        return total > 0 ? 'has-data' : 'needs-setup'
    },
})
