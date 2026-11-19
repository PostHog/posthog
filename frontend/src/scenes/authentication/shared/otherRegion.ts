import { CLOUD_HOSTNAMES } from 'lib/constants'

import { Region } from '~/types'

export function otherRegionOf(region: Region): Region {
    return region === Region.US ? Region.EU : Region.US
}

// Preserve the query string (e.g. `next`) but always land on the login page of the other region.
export function otherRegionLoginUrl(region: Region, search: string): string {
    return `https://${CLOUD_HOSTNAMES[otherRegionOf(region)]}/login${search}`
}
