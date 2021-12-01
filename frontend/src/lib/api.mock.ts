import apiReal from 'lib/api'
import { combineUrl } from 'kea-router'
import { AvailableFeature, OrganizationType, TeamType, UserType } from '~/types'
import { OrganizationMembershipLevel } from './constants'

type APIMockReturnType = {
    [K in keyof Pick<typeof apiReal, 'create' | 'get' | 'update' | 'delete'>]: jest.Mock<
        ReturnType<typeof apiReal[K]>,
        Parameters<typeof apiReal[K]>
    >
}

type APIRoute = {
    pathname: string
    search: string
    searchParams: Record<string, any>
    hash: string
    hashParams: Record<string, any>
    url: string
    data?: Record<string, any>
    method: string
}

interface APIMockOptions {
    availableFeatures: AvailableFeature[]
}

export const MOCK_TEAM_ID: TeamType['id'] = 997
export const MOCK_ORGANIZATION_ID: OrganizationType['id'] = 'ABCD'

export const api = apiReal as any as APIMockReturnType

export const MOCK_DEFAULT_TEAM: Partial<TeamType> = {
    id: MOCK_TEAM_ID,
    ingested_event: true,
    completed_snippet_onboarding: true,
    effective_membership_level: OrganizationMembershipLevel.Admin,
}

export const MOCK_DEFAULT_ORGANIZATION: Partial<OrganizationType> = {
    id: MOCK_ORGANIZATION_ID,
    membership_level: OrganizationMembershipLevel.Admin,
}

export const mockAPI = (cb: (url: APIRoute) => any): void => {
    beforeEach(async () => {
        const methods = ['get', 'update', 'create', 'delete']
        for (const method of methods) {
            api[method as keyof typeof api].mockImplementation(async (url: string, data?: Record<string, any>) => {
                return cb({ ...combineUrl(url), data, method })
            })
        }
    })
}

export function defaultAPIMocks(
    { pathname, searchParams }: APIRoute,
    { availableFeatures }: Partial<APIMockOptions> = {}
): any {
    const organization = { ...MOCK_DEFAULT_ORGANIZATION, available_features: availableFeatures || [] }
    if (pathname === '_preflight/') {
        return { is_clickhouse_enabled: true }
    } else if (pathname === 'api/users/@me/') {
        return {
            organization,
            team: MOCK_DEFAULT_TEAM,
        } as Partial<UserType>
    } else if (pathname === 'api/projects/@current') {
        return MOCK_DEFAULT_TEAM
    } else if (pathname === 'api/organizations/@current') {
        return organization
    } else if (
        [
            `api/projects/${MOCK_TEAM_ID}/actions/`,
            `api/projects/${MOCK_TEAM_ID}/annotations/`,
            `api/projects/${MOCK_TEAM_ID}/event_definitions/`,
            `api/projects/${MOCK_TEAM_ID}/dashboards/`,
            `api/projects/${MOCK_TEAM_ID}/dashboards`,
            `api/projects/${MOCK_TEAM_ID}/groups/`,
            `api/projects/${MOCK_TEAM_ID}/insights/`,
            `api/projects/${MOCK_TEAM_ID}/annotations/`,
            `api/projects/${MOCK_TEAM_ID}/event_definitions/`,
        ].includes(pathname)
    ) {
        return { results: [], next: null }
    }
    throw new Error(`Unmocked fetch to: ${pathname} with params: ${JSON.stringify(searchParams)}`)
}
