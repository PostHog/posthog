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
    AppMetricsResponseApi,
    AppMetricsTotalsResponseApi,
    HogFunctionApi,
    HogFunctionInvocationApi,
    HogFunctionTemplateApi,
    HogFunctionTemplatesListParams,
    HogFunctionsListParams,
    HogFunctionsLogsRetrieveParams,
    HogFunctionsMetricsRetrieveParams,
    HogFunctionsMetricsTotalsRetrieveParams,
    PaginatedHogFunctionMinimalListApi,
    PaginatedHogFunctionTemplateListApi,
    PatchedHogFunctionApi,
    PatchedHogFunctionRearrangeApi,
    PublicHogFunctionTemplatesListParams,
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

export const getHogFunctionTemplatesListUrl = (projectId: string, params?: HogFunctionTemplatesListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/hog_function_templates/?${stringifiedParams}`
        : `/api/projects/${projectId}/hog_function_templates/`
}

export const hogFunctionTemplatesList = async (
    projectId: string,
    params?: HogFunctionTemplatesListParams,
    options?: RequestInit
): Promise<PaginatedHogFunctionTemplateListApi> => {
    return apiMutator<PaginatedHogFunctionTemplateListApi>(getHogFunctionTemplatesListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getHogFunctionTemplatesRetrieveUrl = (projectId: string, templateId: string) => {
    return `/api/projects/${projectId}/hog_function_templates/${templateId}/`
}

export const hogFunctionTemplatesRetrieve = async (
    projectId: string,
    templateId: string,
    options?: RequestInit
): Promise<HogFunctionTemplateApi> => {
    return apiMutator<HogFunctionTemplateApi>(getHogFunctionTemplatesRetrieveUrl(projectId, templateId), {
        ...options,
        method: 'GET',
    })
}

export const getHogFunctionsListUrl = (projectId: string, params?: HogFunctionsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/hog_functions/?${stringifiedParams}`
        : `/api/projects/${projectId}/hog_functions/`
}

export const hogFunctionsList = async (
    projectId: string,
    params?: HogFunctionsListParams,
    options?: RequestInit
): Promise<PaginatedHogFunctionMinimalListApi> => {
    return apiMutator<PaginatedHogFunctionMinimalListApi>(getHogFunctionsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getHogFunctionsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/hog_functions/`
}

export const hogFunctionsCreate = async (
    projectId: string,
    hogFunctionApi: NonReadonly<HogFunctionApi>,
    options?: RequestInit
): Promise<HogFunctionApi> => {
    return apiMutator<HogFunctionApi>(getHogFunctionsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(hogFunctionApi),
    })
}

export const getHogFunctionsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/hog_functions/${id}/`
}

export const hogFunctionsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<HogFunctionApi> => {
    return apiMutator<HogFunctionApi>(getHogFunctionsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getHogFunctionsUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/hog_functions/${id}/`
}

export const hogFunctionsUpdate = async (
    projectId: string,
    id: string,
    hogFunctionApi: NonReadonly<HogFunctionApi>,
    options?: RequestInit
): Promise<HogFunctionApi> => {
    return apiMutator<HogFunctionApi>(getHogFunctionsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(hogFunctionApi),
    })
}

export const getHogFunctionsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/hog_functions/${id}/`
}

export const hogFunctionsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedHogFunctionApi: NonReadonly<PatchedHogFunctionApi>,
    options?: RequestInit
): Promise<HogFunctionApi> => {
    return apiMutator<HogFunctionApi>(getHogFunctionsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedHogFunctionApi),
    })
}

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export const getHogFunctionsDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/hog_functions/${id}/`
}

export const hogFunctionsDestroy = async (projectId: string, id: string, options?: RequestInit): Promise<unknown> => {
    return apiMutator<unknown>(getHogFunctionsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getHogFunctionsEnableBackfillsCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/hog_functions/${id}/enable_backfills/`
}

export const hogFunctionsEnableBackfillsCreate = async (
    projectId: string,
    id: string,
    hogFunctionApi: NonReadonly<HogFunctionApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getHogFunctionsEnableBackfillsCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(hogFunctionApi),
    })
}

export const getHogFunctionsInvocationsCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/hog_functions/${id}/invocations/`
}

export const hogFunctionsInvocationsCreate = async (
    projectId: string,
    id: string,
    hogFunctionInvocationApi: NonReadonly<HogFunctionInvocationApi>,
    options?: RequestInit
): Promise<HogFunctionInvocationApi> => {
    return apiMutator<HogFunctionInvocationApi>(getHogFunctionsInvocationsCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(hogFunctionInvocationApi),
    })
}

export const getHogFunctionsLogsRetrieveUrl = (
    projectId: string,
    id: string,
    params?: HogFunctionsLogsRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/hog_functions/${id}/logs/?${stringifiedParams}`
        : `/api/projects/${projectId}/hog_functions/${id}/logs/`
}

export const hogFunctionsLogsRetrieve = async (
    projectId: string,
    id: string,
    params?: HogFunctionsLogsRetrieveParams,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getHogFunctionsLogsRetrieveUrl(projectId, id, params), {
        ...options,
        method: 'GET',
    })
}

export const getHogFunctionsMetricsRetrieveUrl = (
    projectId: string,
    id: string,
    params?: HogFunctionsMetricsRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/hog_functions/${id}/metrics/?${stringifiedParams}`
        : `/api/projects/${projectId}/hog_functions/${id}/metrics/`
}

export const hogFunctionsMetricsRetrieve = async (
    projectId: string,
    id: string,
    params?: HogFunctionsMetricsRetrieveParams,
    options?: RequestInit
): Promise<AppMetricsResponseApi> => {
    return apiMutator<AppMetricsResponseApi>(getHogFunctionsMetricsRetrieveUrl(projectId, id, params), {
        ...options,
        method: 'GET',
    })
}

export const getHogFunctionsMetricsTotalsRetrieveUrl = (
    projectId: string,
    id: string,
    params?: HogFunctionsMetricsTotalsRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/hog_functions/${id}/metrics/totals/?${stringifiedParams}`
        : `/api/projects/${projectId}/hog_functions/${id}/metrics/totals/`
}

export const hogFunctionsMetricsTotalsRetrieve = async (
    projectId: string,
    id: string,
    params?: HogFunctionsMetricsTotalsRetrieveParams,
    options?: RequestInit
): Promise<AppMetricsTotalsResponseApi> => {
    return apiMutator<AppMetricsTotalsResponseApi>(getHogFunctionsMetricsTotalsRetrieveUrl(projectId, id, params), {
        ...options,
        method: 'GET',
    })
}

export const getHogFunctionsIconRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/hog_functions/icon/`
}

export const hogFunctionsIconRetrieve = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getHogFunctionsIconRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getHogFunctionsIconsRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/hog_functions/icons/`
}

export const hogFunctionsIconsRetrieve = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getHogFunctionsIconsRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

/**
 * Update the execution order of multiple HogFunctions.
 */
export const getHogFunctionsRearrangePartialUpdateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/hog_functions/rearrange/`
}

export const hogFunctionsRearrangePartialUpdate = async (
    projectId: string,
    patchedHogFunctionRearrangeApi: PatchedHogFunctionRearrangeApi,
    options?: RequestInit
): Promise<HogFunctionApi[]> => {
    return apiMutator<HogFunctionApi[]>(getHogFunctionsRearrangePartialUpdateUrl(projectId), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedHogFunctionRearrangeApi),
    })
}

export const getPublicHogFunctionTemplatesListUrl = (params?: PublicHogFunctionTemplatesListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/public_hog_function_templates/?${stringifiedParams}`
        : `/api/public_hog_function_templates/`
}

export const publicHogFunctionTemplatesList = async (
    params?: PublicHogFunctionTemplatesListParams,
    options?: RequestInit
): Promise<PaginatedHogFunctionTemplateListApi> => {
    return apiMutator<PaginatedHogFunctionTemplateListApi>(getPublicHogFunctionTemplatesListUrl(params), {
        ...options,
        method: 'GET',
    })
}
