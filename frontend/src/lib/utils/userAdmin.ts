import posthog from 'posthog-js'

import api from 'lib/api'
import { CLOUD_HOSTNAMES } from 'lib/constants'
import { hogql } from 'lib/utils/hogql'

import { HogQLQueryResponse, NodeKind, QueryLogTags } from '~/queries/schema/schema-general'
import { Region } from '~/types'

const POSTHOG_CLOUD_REGIONS = new Map<string, Region.US | Region.EU>([
    [CLOUD_HOSTNAMES[Region.US], Region.US],
    [CLOUD_HOSTNAMES[Region.EU], Region.EU],
    ['app.posthog.com', Region.US],
])

// EU users have no rows in this region's posthog_user tables; eu_org_members is a
// materialized DWH pre-join of the EU postgres sync (prod-only, refreshed daily).
const EU_ORG_MEMBERS_VIEW = 'eu_org_members'

export function getCurrentCloudRegion(
    currentOrigin: string = window.location.origin
): Region.US | Region.EU | undefined {
    return POSTHOG_CLOUD_REGIONS.get(new URL(currentOrigin).hostname)
}

function getAdminOrigin(region: Region.US | Region.EU, currentOrigin: string): string {
    const currentUrl = new URL(currentOrigin)
    return POSTHOG_CLOUD_REGIONS.has(currentUrl.hostname) ? `https://${CLOUD_HOSTNAMES[region]}` : currentUrl.origin
}

export function getUserAdminUrl(
    region: Region.US | Region.EU,
    userId: number,
    currentOrigin: string = window.location.origin
): string {
    return `${getAdminOrigin(region, currentOrigin)}/admin/posthog/user/${userId}/change/`
}

export function getUserLogInAsUrl(
    region: Region.US | Region.EU,
    userId: number,
    currentOrigin: string = window.location.origin
): string {
    return `${getAdminOrigin(region, currentOrigin)}/admin/console/users/${userId}/log-in-as/log-in/`
}

// The in-app log in as flow posts with this origin's session and CSRF cookie, so it only reaches this origin's users.
export function canLogInAsFromCurrentOrigin(
    region: Region.US | Region.EU,
    currentOrigin: string = window.location.origin
): boolean {
    const currentRegion = getCurrentCloudRegion(currentOrigin)
    return currentRegion === undefined || currentRegion === region
}

export function isEuOrgMembersViewMissingError(error: unknown): boolean {
    const message = error instanceof Error ? error.message : String(error ?? '')
    return (
        message.includes(EU_ORG_MEMBERS_VIEW) &&
        (message.includes("don't have access to table") || message.includes('Unknown table'))
    )
}

export async function getEuUserId(distinctIds: string[], tags: QueryLogTags): Promise<number | null> {
    try {
        const response = (await api.query({
            kind: NodeKind.HogQLQuery,
            tags,
            query: hogql`
                select user_id
                from eu_org_members
                where distinct_id in ${distinctIds}
                limit 1
            `,
        })) as HogQLQueryResponse
        const userId = response.results?.[0]?.[0]
        return userId == null ? null : Number(userId)
    } catch (error) {
        if (!isEuOrgMembersViewMissingError(error)) {
            posthog.captureException(error as Error, { scope: 'userAdmin.getEuUserId' })
        }
        return null
    }
}
