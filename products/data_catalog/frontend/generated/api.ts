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
    DataCatalogMetricApi,
    DataCatalogMetricsListParams,
    PaginatedDataCatalogMetricListApi,
    PatchedDataCatalogMetricApi,
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

export const getDataCatalogMetricsListUrl = (projectId: string, params?: DataCatalogMetricsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/data_catalog/metrics/?${stringifiedParams}`
        : `/api/projects/${projectId}/data_catalog/metrics/`
}

/**
 * CRUD for catalog metrics, addressed by their reserved ``name`` (e.g. /metrics/mrr/).
 */
export const dataCatalogMetricsList = async (
    projectId: string,
    params?: DataCatalogMetricsListParams,
    options?: RequestInit
): Promise<PaginatedDataCatalogMetricListApi> => {
    return apiMutator<PaginatedDataCatalogMetricListApi>(getDataCatalogMetricsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getDataCatalogMetricsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/data_catalog/metrics/`
}

/**
 * Create a metric, or refine the one already holding this name for the team.
 */
export const dataCatalogMetricsCreate = async (
    projectId: string,
    dataCatalogMetricApi: NonReadonly<DataCatalogMetricApi>,
    options?: RequestInit
): Promise<DataCatalogMetricApi> => {
    return apiMutator<DataCatalogMetricApi>(getDataCatalogMetricsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(dataCatalogMetricApi),
    })
}

export const getDataCatalogMetricsRetrieveUrl = (projectId: string, name: string) => {
    return `/api/projects/${projectId}/data_catalog/metrics/${name}/`
}

/**
 * CRUD for catalog metrics, addressed by their reserved ``name`` (e.g. /metrics/mrr/).
 */
export const dataCatalogMetricsRetrieve = async (
    projectId: string,
    name: string,
    options?: RequestInit
): Promise<DataCatalogMetricApi> => {
    return apiMutator<DataCatalogMetricApi>(getDataCatalogMetricsRetrieveUrl(projectId, name), {
        ...options,
        method: 'GET',
    })
}

export const getDataCatalogMetricsUpdateUrl = (projectId: string, name: string) => {
    return `/api/projects/${projectId}/data_catalog/metrics/${name}/`
}

/**
 * CRUD for catalog metrics, addressed by their reserved ``name`` (e.g. /metrics/mrr/).
 */
export const dataCatalogMetricsUpdate = async (
    projectId: string,
    name: string,
    dataCatalogMetricApi: NonReadonly<DataCatalogMetricApi>,
    options?: RequestInit
): Promise<DataCatalogMetricApi> => {
    return apiMutator<DataCatalogMetricApi>(getDataCatalogMetricsUpdateUrl(projectId, name), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(dataCatalogMetricApi),
    })
}

export const getDataCatalogMetricsPartialUpdateUrl = (projectId: string, name: string) => {
    return `/api/projects/${projectId}/data_catalog/metrics/${name}/`
}

/**
 * CRUD for catalog metrics, addressed by their reserved ``name`` (e.g. /metrics/mrr/).
 */
export const dataCatalogMetricsPartialUpdate = async (
    projectId: string,
    name: string,
    patchedDataCatalogMetricApi?: NonReadonly<PatchedDataCatalogMetricApi>,
    options?: RequestInit
): Promise<DataCatalogMetricApi> => {
    return apiMutator<DataCatalogMetricApi>(getDataCatalogMetricsPartialUpdateUrl(projectId, name), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedDataCatalogMetricApi),
    })
}

export const getDataCatalogMetricsDestroyUrl = (projectId: string, name: string) => {
    return `/api/projects/${projectId}/data_catalog/metrics/${name}/`
}

/**
 * CRUD for catalog metrics, addressed by their reserved ``name`` (e.g. /metrics/mrr/).
 */
export const dataCatalogMetricsDestroy = async (
    projectId: string,
    name: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getDataCatalogMetricsDestroyUrl(projectId, name), {
        ...options,
        method: 'DELETE',
    })
}
