import { apiMutator } from '../../../../frontend/src/lib/api-orval-mutator'
/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import type {
    CrossProjectDashboardApi,
    CrossProjectDashboardTileApi,
    CrossProjectDashboardsListParams,
    CrossProjectDashboardsTilesListParams,
    PaginatedCrossProjectDashboardListApi,
    PaginatedCrossProjectDashboardTileListApi,
    PatchedCrossProjectDashboardApi,
    PatchedCrossProjectDashboardTileApi,
} from './api.schemas'

// https://stackoverflow.com/questions/49579094/typescript-conditional-types-filter-out-readonly-properties-pick-only-requir/49579497#49579497
type IfEquals<X, Y, A = X, B = never> = (<T>() => T extends X ? 1 : 2) extends <T>() => T extends Y ? 1 : 2 ? A : B

type WritableKeys<T> = {
    [P in keyof T]-?: IfEquals<{ [Q in P]: T[P] }, { -readonly [Q in P]: T[P] }, P>
}[keyof T]

type UnionToIntersection<U> = (U extends any ? (k: U) => void : never) extends (k: infer I) => void ? I : never
type DistributeReadOnlyOverUnions<T> = T extends any ? NonReadonly<T> : never

type Writable<T> = Pick<T, WritableKeys<T>>
type NonReadonly<T> = [T] extends [UnionToIntersection<T>]
    ? {
          [P in keyof Writable<T>]: T[P] extends object ? NonReadonly<NonNullable<T[P]>> : T[P]
      }
    : DistributeReadOnlyOverUnions<T>

export const getCrossProjectDashboardsListUrl = (organizationId: string, params?: CrossProjectDashboardsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/organizations/${organizationId}/cross_project_dashboards/?${stringifiedParams}`
        : `/api/organizations/${organizationId}/cross_project_dashboards/`
}

/**
 * Dashboards the organization owns, holding insights from one or more projects.
 */
export const crossProjectDashboardsList = async (
    organizationId: string,
    params?: CrossProjectDashboardsListParams,
    options?: RequestInit
): Promise<PaginatedCrossProjectDashboardListApi> => {
    return apiMutator<PaginatedCrossProjectDashboardListApi>(getCrossProjectDashboardsListUrl(organizationId, params), {
        ...options,
        method: 'GET',
    })
}

export const getCrossProjectDashboardsCreateUrl = (organizationId: string) => {
    return `/api/organizations/${organizationId}/cross_project_dashboards/`
}

/**
 * Dashboards the organization owns, holding insights from one or more projects.
 */
export const crossProjectDashboardsCreate = async (
    organizationId: string,
    crossProjectDashboardApi: NonReadonly<CrossProjectDashboardApi>,
    options?: RequestInit
): Promise<CrossProjectDashboardApi> => {
    return apiMutator<CrossProjectDashboardApi>(getCrossProjectDashboardsCreateUrl(organizationId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(crossProjectDashboardApi),
    })
}

export const getCrossProjectDashboardsTilesListUrl = (
    organizationId: string,
    dashboardId: string,
    params?: CrossProjectDashboardsTilesListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/organizations/${organizationId}/cross_project_dashboards/${dashboardId}/tiles/?${stringifiedParams}`
        : `/api/organizations/${organizationId}/cross_project_dashboards/${dashboardId}/tiles/`
}

/**
 * Tiles on one cross-project dashboard, edited one at a time.
 *
 * Writes are per tile rather than a whole-set replace, so two people editing the same
 * dashboard cannot overwrite each other's tiles.
 */
export const crossProjectDashboardsTilesList = async (
    organizationId: string,
    dashboardId: string,
    params?: CrossProjectDashboardsTilesListParams,
    options?: RequestInit
): Promise<PaginatedCrossProjectDashboardTileListApi> => {
    return apiMutator<PaginatedCrossProjectDashboardTileListApi>(
        getCrossProjectDashboardsTilesListUrl(organizationId, dashboardId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getCrossProjectDashboardsTilesCreateUrl = (organizationId: string, dashboardId: string) => {
    return `/api/organizations/${organizationId}/cross_project_dashboards/${dashboardId}/tiles/`
}

/**
 * Tiles on one cross-project dashboard, edited one at a time.
 *
 * Writes are per tile rather than a whole-set replace, so two people editing the same
 * dashboard cannot overwrite each other's tiles.
 */
export const crossProjectDashboardsTilesCreate = async (
    organizationId: string,
    dashboardId: string,
    crossProjectDashboardTileApi: NonReadonly<CrossProjectDashboardTileApi>,
    options?: RequestInit
): Promise<CrossProjectDashboardTileApi> => {
    return apiMutator<CrossProjectDashboardTileApi>(
        getCrossProjectDashboardsTilesCreateUrl(organizationId, dashboardId),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(crossProjectDashboardTileApi),
        }
    )
}

export const getCrossProjectDashboardsTilesRetrieveUrl = (organizationId: string, dashboardId: string, id: string) => {
    return `/api/organizations/${organizationId}/cross_project_dashboards/${dashboardId}/tiles/${id}/`
}

/**
 * Tiles on one cross-project dashboard, edited one at a time.
 *
 * Writes are per tile rather than a whole-set replace, so two people editing the same
 * dashboard cannot overwrite each other's tiles.
 */
export const crossProjectDashboardsTilesRetrieve = async (
    organizationId: string,
    dashboardId: string,
    id: string,
    options?: RequestInit
): Promise<CrossProjectDashboardTileApi> => {
    return apiMutator<CrossProjectDashboardTileApi>(
        getCrossProjectDashboardsTilesRetrieveUrl(organizationId, dashboardId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getCrossProjectDashboardsTilesUpdateUrl = (organizationId: string, dashboardId: string, id: string) => {
    return `/api/organizations/${organizationId}/cross_project_dashboards/${dashboardId}/tiles/${id}/`
}

/**
 * Tiles on one cross-project dashboard, edited one at a time.
 *
 * Writes are per tile rather than a whole-set replace, so two people editing the same
 * dashboard cannot overwrite each other's tiles.
 */
export const crossProjectDashboardsTilesUpdate = async (
    organizationId: string,
    dashboardId: string,
    id: string,
    crossProjectDashboardTileApi: NonReadonly<CrossProjectDashboardTileApi>,
    options?: RequestInit
): Promise<CrossProjectDashboardTileApi> => {
    return apiMutator<CrossProjectDashboardTileApi>(
        getCrossProjectDashboardsTilesUpdateUrl(organizationId, dashboardId, id),
        {
            ...options,
            method: 'PUT',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(crossProjectDashboardTileApi),
        }
    )
}

export const getCrossProjectDashboardsTilesPartialUpdateUrl = (
    organizationId: string,
    dashboardId: string,
    id: string
) => {
    return `/api/organizations/${organizationId}/cross_project_dashboards/${dashboardId}/tiles/${id}/`
}

/**
 * Tiles on one cross-project dashboard, edited one at a time.
 *
 * Writes are per tile rather than a whole-set replace, so two people editing the same
 * dashboard cannot overwrite each other's tiles.
 */
export const crossProjectDashboardsTilesPartialUpdate = async (
    organizationId: string,
    dashboardId: string,
    id: string,
    patchedCrossProjectDashboardTileApi?: NonReadonly<PatchedCrossProjectDashboardTileApi>,
    options?: RequestInit
): Promise<CrossProjectDashboardTileApi> => {
    return apiMutator<CrossProjectDashboardTileApi>(
        getCrossProjectDashboardsTilesPartialUpdateUrl(organizationId, dashboardId, id),
        {
            ...options,
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(patchedCrossProjectDashboardTileApi),
        }
    )
}

export const getCrossProjectDashboardsTilesDestroyUrl = (organizationId: string, dashboardId: string, id: string) => {
    return `/api/organizations/${organizationId}/cross_project_dashboards/${dashboardId}/tiles/${id}/`
}

/**
 * Tiles on one cross-project dashboard, edited one at a time.
 *
 * Writes are per tile rather than a whole-set replace, so two people editing the same
 * dashboard cannot overwrite each other's tiles.
 */
export const crossProjectDashboardsTilesDestroy = async (
    organizationId: string,
    dashboardId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getCrossProjectDashboardsTilesDestroyUrl(organizationId, dashboardId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getCrossProjectDashboardsRetrieveUrl = (organizationId: string, id: string) => {
    return `/api/organizations/${organizationId}/cross_project_dashboards/${id}/`
}

/**
 * Dashboards the organization owns, holding insights from one or more projects.
 */
export const crossProjectDashboardsRetrieve = async (
    organizationId: string,
    id: string,
    options?: RequestInit
): Promise<CrossProjectDashboardApi> => {
    return apiMutator<CrossProjectDashboardApi>(getCrossProjectDashboardsRetrieveUrl(organizationId, id), {
        ...options,
        method: 'GET',
    })
}

export const getCrossProjectDashboardsUpdateUrl = (organizationId: string, id: string) => {
    return `/api/organizations/${organizationId}/cross_project_dashboards/${id}/`
}

/**
 * Dashboards the organization owns, holding insights from one or more projects.
 */
export const crossProjectDashboardsUpdate = async (
    organizationId: string,
    id: string,
    crossProjectDashboardApi: NonReadonly<CrossProjectDashboardApi>,
    options?: RequestInit
): Promise<CrossProjectDashboardApi> => {
    return apiMutator<CrossProjectDashboardApi>(getCrossProjectDashboardsUpdateUrl(organizationId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(crossProjectDashboardApi),
    })
}

export const getCrossProjectDashboardsPartialUpdateUrl = (organizationId: string, id: string) => {
    return `/api/organizations/${organizationId}/cross_project_dashboards/${id}/`
}

/**
 * Dashboards the organization owns, holding insights from one or more projects.
 */
export const crossProjectDashboardsPartialUpdate = async (
    organizationId: string,
    id: string,
    patchedCrossProjectDashboardApi?: NonReadonly<PatchedCrossProjectDashboardApi>,
    options?: RequestInit
): Promise<CrossProjectDashboardApi> => {
    return apiMutator<CrossProjectDashboardApi>(getCrossProjectDashboardsPartialUpdateUrl(organizationId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedCrossProjectDashboardApi),
    })
}

export const getCrossProjectDashboardsDestroyUrl = (organizationId: string, id: string) => {
    return `/api/organizations/${organizationId}/cross_project_dashboards/${id}/`
}

/**
 * Dashboards the organization owns, holding insights from one or more projects.
 */
export const crossProjectDashboardsDestroy = async (
    organizationId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getCrossProjectDashboardsDestroyUrl(organizationId, id), {
        ...options,
        method: 'DELETE',
    })
}
