import { FeatureCollection } from 'geojson'
import { afterMount, kea, path } from 'kea'
import { loaders } from 'kea-loaders'

import type { adminGeoDataLogicType } from './adminGeoDataLogicType'

const BASE_URL = 'https://posthog-prod-maps.s3.us-east-1.amazonaws.com'
const ADMIN_GEOJSON_URL = `${BASE_URL}/admin1_50m.json`

export const adminGeoDataLogic = kea<adminGeoDataLogicType>([
    path(['scenes', 'insights', 'WorldMap', 'adminGeoDataLogic']),
    loaders({
        adminGeoData: [
            null as FeatureCollection | null,
            {
                loadAdminGeoData: async () => {
                    const response = await fetch(ADMIN_GEOJSON_URL)
                    if (!response.ok) {
                        throw new Error(`Failed to load admin geo data: ${response.status}`)
                    }
                    return response.json()
                },
            },
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadAdminGeoData()
    }),
])
