import apiReal from 'lib/api'
import { combineUrl } from 'kea-router'
import { AvailableFeature, OrganizationType, TeamType } from '~/types'

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

export const MOCK_DEFAULT_TEAM = {
    id: MOCK_TEAM_ID,
    ingested_event: true,
    completed_snippet_onboarding: true,
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
    if (pathname === '_preflight/') {
        return { is_clickhouse_enabled: true }
    } else if (pathname === 'api/users/@me/') {
        return {
            organization: { available_features: availableFeatures || [] },
            team: { ingested_event: true, completed_snippet_onboarding: true },
        }
    } else if (pathname === 'api/projects/@current') {
        return MOCK_DEFAULT_TEAM
    } else if (pathname === 'api/organizations/@current') {
        return {
            id: MOCK_ORGANIZATION_ID,
        }
    } else if (
        [
            `api/projects/${MOCK_TEAM_ID}/actions/`,
            `api/projects/${MOCK_TEAM_ID}/event_definitions/`,
            `api/projects/${MOCK_TEAM_ID}/dashboards/`,
            `api/projects/${MOCK_TEAM_ID}/dashboards`,
            'api/projects/@current/event_definitions/',
        ].includes(pathname)
    ) {
        return { results: [] }
    }
    throw new Error(`Unmocked fetch to: ${pathname} with params: ${JSON.stringify(searchParams)}`)
}
