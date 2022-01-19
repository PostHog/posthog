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

enum APIMethod {
    Create = 'create',
    Get = 'get',
    Update = 'update',
    Delete = 'delete',
}
const apiMethods = [APIMethod.Create, APIMethod.Get, APIMethod.Update, APIMethod.Delete]

type APIRoute = {
    pathname: string
    search: string
    searchParams: Record<string, any>
    hash: string
    hashParams: Record<string, any>
    url: string
    data?: Record<string, any>
    method: APIMethod
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

export const mockAPI = (
    urlCallback?: (url: APIRoute) => any,
    apiCallback?: (apiCallPath: string, args: any[]) => void,
    availableFeatures: AvailableFeature[] = []
): void => {
    beforeEach(async () => {
        for (const method of apiMethods) {
            api[method as keyof typeof api].mockImplementation(async (url: string, data?: Record<string, any>) => {
                const urlParams = { ...combineUrl(url), data, method }
                return (await urlCallback?.(urlParams)) ?? defaultAPIMocks(urlParams, availableFeatures)
            })
        }

        for (const chain of ['actions', 'cohorts', 'pluginLogs']) {
            api[chain] = new Proxy(
                {},
                {
                    get: function (_, property) {
                        const path = [chain, property].join('.')
                        return async (...args: any[]) =>
                            (await apiCallback?.(path, args)) ?? defaultAPICallMocks(path, args)
                    },
                }
            )
        }
    })
}

export function defaultAPIMocks({ pathname, searchParams }: APIRoute, availableFeatures: AvailableFeature[] = []): any {
    const organization = { ...MOCK_DEFAULT_ORGANIZATION, available_features: availableFeatures }
    if (pathname === '_preflight/') {
        return {}
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
    throwLog(`Unmocked fetch to: ${pathname} with params: ${JSON.stringify(searchParams)}`)
}

export function defaultAPICallMocks(path: string, args: any[]): any {
    if (['actions.list', 'cohorts.list'].includes(path)) {
        return { results: [], next: null }
    }
    throwLog(`Unmocked API call on: api.${path}() with args: ${JSON.stringify(args)}`)
}

function throwLog(string: string): void {
    console.error(string)
    throw new Error(string)
}
