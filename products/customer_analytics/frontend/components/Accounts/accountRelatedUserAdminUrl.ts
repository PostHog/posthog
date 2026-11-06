import { CLOUD_HOSTNAMES } from 'lib/constants'

import { Region } from '~/types'

const POSTHOG_CLOUD_HOSTNAMES = new Set([CLOUD_HOSTNAMES[Region.US], CLOUD_HOSTNAMES[Region.EU]])

function getAdminOrigin(region: Region.US | Region.EU, currentOrigin: string): string {
    const currentUrl = new URL(currentOrigin)
    return POSTHOG_CLOUD_HOSTNAMES.has(currentUrl.hostname) ? `https://${CLOUD_HOSTNAMES[region]}` : currentUrl.origin
}

export function getAccountRelatedUserAdminUrl(
    region: Region.US | Region.EU,
    userId: number,
    currentOrigin: string = window.location.origin
): string {
    return `${getAdminOrigin(region, currentOrigin)}/admin/posthog/user/${userId}/change/`
}

export function getAccountUserRegion(instanceUrl: unknown): Region.US | Region.EU {
    return typeof instanceUrl === 'string' && instanceUrl.includes(CLOUD_HOSTNAMES[Region.EU]) ? Region.EU : Region.US
}

export function getAccountUserAdminSearchUrl(
    region: Region.US | Region.EU,
    email: string,
    currentOrigin: string = window.location.origin
): string {
    return `${getAdminOrigin(region, currentOrigin)}/admin/posthog/user/?q=${encodeURIComponent(email)}`
}
