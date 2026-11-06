import { CLOUD_HOSTNAMES } from 'lib/constants'

import { Region } from '~/types'

const POSTHOG_CLOUD_HOSTNAMES = new Set([CLOUD_HOSTNAMES[Region.US], CLOUD_HOSTNAMES[Region.EU]])

export function getAccountRelatedUserAdminUrl(
    region: Region.US | Region.EU,
    userId: number,
    currentOrigin: string = window.location.origin
): string {
    const currentUrl = new URL(currentOrigin)
    const adminOrigin = POSTHOG_CLOUD_HOSTNAMES.has(currentUrl.hostname)
        ? `https://${CLOUD_HOSTNAMES[region]}`
        : currentUrl.origin

    return `${adminOrigin}/admin/posthog/user/${userId}/change/`
}
