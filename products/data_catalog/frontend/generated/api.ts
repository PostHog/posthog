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
    CertificationCreateApi,
    DataCatalogCertificationApi,
    DataCatalogCertificationsListParams,
    DataCatalogMetricApi,
    DataCatalogMetricRunApi,
    DataCatalogMetricRunRequestApi,
    DataCatalogMetricsListParams,
    DataCatalogMetricsRunCreateParams,
    DataCatalogRelationshipProposalApi,
    DataCatalogRelationshipProposalsListParams,
    PaginatedDataCatalogCertificationListApi,
    PaginatedDataCatalogMetricListApi,
    PaginatedDataCatalogRelationshipProposalListApi,
    PatchedDataCatalogMetricApi,
    RelationshipRejectApi,
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

export const getDataCatalogCertificationsListUrl = (
    projectId: string,
    params?: DataCatalogCertificationsListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/data_catalog/certifications/?${stringifiedParams}`
        : `/api/projects/${projectId}/data_catalog/certifications/`
}

/**
 * Trust marks on warehouse tables and views. Reads exclude soft-deleted targets.
 */
export const dataCatalogCertificationsList = async (
    projectId: string,
    params?: DataCatalogCertificationsListParams,
    options?: RequestInit
): Promise<PaginatedDataCatalogCertificationListApi> => {
    return apiMutator<PaginatedDataCatalogCertificationListApi>(
        getDataCatalogCertificationsListUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getDataCatalogCertificationsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/data_catalog/certifications/`
}

/**
 * Trust marks on warehouse tables and views. Reads exclude soft-deleted targets.
 */
export const dataCatalogCertificationsCreate = async (
    projectId: string,
    certificationCreateApi?: CertificationCreateApi,
    options?: RequestInit
): Promise<DataCatalogCertificationApi> => {
    return apiMutator<DataCatalogCertificationApi>(getDataCatalogCertificationsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(certificationCreateApi),
    })
}

export const getDataCatalogCertificationsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/data_catalog/certifications/${id}/`
}

/**
 * Trust marks on warehouse tables and views. Reads exclude soft-deleted targets.
 */
export const dataCatalogCertificationsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<DataCatalogCertificationApi> => {
    return apiMutator<DataCatalogCertificationApi>(getDataCatalogCertificationsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getDataCatalogCertificationsDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/data_catalog/certifications/${id}/`
}

/**
 * Trust marks on warehouse tables and views. Reads exclude soft-deleted targets.
 */
export const dataCatalogCertificationsDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getDataCatalogCertificationsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getDataCatalogCertificationsCertifyCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/data_catalog/certifications/${id}/certify/`
}

/**
 * Mark the target as certified (prefer this source).
 */
export const dataCatalogCertificationsCertifyCreate = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<DataCatalogCertificationApi> => {
    return apiMutator<DataCatalogCertificationApi>(getDataCatalogCertificationsCertifyCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
    })
}

export const getDataCatalogCertificationsDeprecateCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/data_catalog/certifications/${id}/deprecate/`
}

/**
 * Mark the target as deprecated (avoid this source).
 */
export const dataCatalogCertificationsDeprecateCreate = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<DataCatalogCertificationApi> => {
    return apiMutator<DataCatalogCertificationApi>(getDataCatalogCertificationsDeprecateCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
    })
}

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

export const getDataCatalogMetricsApproveCreateUrl = (projectId: string, name: string) => {
    return `/api/projects/${projectId}/data_catalog/metrics/${name}/approve/`
}

/**
 * Bless a metric as canonical. Returns 409 while the metric is drifted from its insight.
 */
export const dataCatalogMetricsApproveCreate = async (
    projectId: string,
    name: string,
    options?: RequestInit
): Promise<DataCatalogMetricApi> => {
    return apiMutator<DataCatalogMetricApi>(getDataCatalogMetricsApproveCreateUrl(projectId, name), {
        ...options,
        method: 'POST',
    })
}

export const getDataCatalogMetricsRefreshFromInsightCreateUrl = (projectId: string, name: string) => {
    return `/api/projects/${projectId}/data_catalog/metrics/${name}/refresh_from_insight/`
}

/**
 * Re-snapshot the linked insight's current query into the definition.
 */
export const dataCatalogMetricsRefreshFromInsightCreate = async (
    projectId: string,
    name: string,
    options?: RequestInit
): Promise<DataCatalogMetricApi> => {
    return apiMutator<DataCatalogMetricApi>(getDataCatalogMetricsRefreshFromInsightCreateUrl(projectId, name), {
        ...options,
        method: 'POST',
    })
}

export const getDataCatalogMetricsRunCreateUrl = (
    projectId: string,
    name: string,
    params?: DataCatalogMetricsRunCreateParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/data_catalog/metrics/${name}/run/?${stringifiedParams}`
        : `/api/projects/${projectId}/data_catalog/metrics/${name}/run/`
}

/**
 * Execute the metric's definition and return the normalized result envelope.
 */
export const dataCatalogMetricsRunCreate = async (
    projectId: string,
    name: string,
    dataCatalogMetricRunRequestApi?: DataCatalogMetricRunRequestApi,
    params?: DataCatalogMetricsRunCreateParams,
    options?: RequestInit
): Promise<DataCatalogMetricRunApi> => {
    return apiMutator<DataCatalogMetricRunApi>(getDataCatalogMetricsRunCreateUrl(projectId, name, params), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(dataCatalogMetricRunRequestApi),
    })
}

export const getDataCatalogRelationshipProposalsListUrl = (
    projectId: string,
    params?: DataCatalogRelationshipProposalsListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/data_catalog/relationship_proposals/?${stringifiedParams}`
        : `/api/projects/${projectId}/data_catalog/relationship_proposals/`
}

/**
 * Reviewed join facts. Accepting one promotes it to a real DataWarehouseJoin; rejections persist.
 */
export const dataCatalogRelationshipProposalsList = async (
    projectId: string,
    params?: DataCatalogRelationshipProposalsListParams,
    options?: RequestInit
): Promise<PaginatedDataCatalogRelationshipProposalListApi> => {
    return apiMutator<PaginatedDataCatalogRelationshipProposalListApi>(
        getDataCatalogRelationshipProposalsListUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getDataCatalogRelationshipProposalsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/data_catalog/relationship_proposals/`
}

/**
 * Reviewed join facts. Accepting one promotes it to a real DataWarehouseJoin; rejections persist.
 */
export const dataCatalogRelationshipProposalsCreate = async (
    projectId: string,
    dataCatalogRelationshipProposalApi: NonReadonly<DataCatalogRelationshipProposalApi>,
    options?: RequestInit
): Promise<DataCatalogRelationshipProposalApi> => {
    return apiMutator<DataCatalogRelationshipProposalApi>(getDataCatalogRelationshipProposalsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(dataCatalogRelationshipProposalApi),
    })
}

export const getDataCatalogRelationshipProposalsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/data_catalog/relationship_proposals/${id}/`
}

/**
 * Reviewed join facts. Accepting one promotes it to a real DataWarehouseJoin; rejections persist.
 */
export const dataCatalogRelationshipProposalsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<DataCatalogRelationshipProposalApi> => {
    return apiMutator<DataCatalogRelationshipProposalApi>(
        getDataCatalogRelationshipProposalsRetrieveUrl(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getDataCatalogRelationshipProposalsAcceptCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/data_catalog/relationship_proposals/${id}/accept/`
}

/**
 * Promote the proposal to a real warehouse join after re-validating and probing it.
 */
export const dataCatalogRelationshipProposalsAcceptCreate = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<DataCatalogRelationshipProposalApi> => {
    return apiMutator<DataCatalogRelationshipProposalApi>(
        getDataCatalogRelationshipProposalsAcceptCreateUrl(projectId, id),
        {
            ...options,
            method: 'POST',
        }
    )
}

export const getDataCatalogRelationshipProposalsRejectCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/data_catalog/relationship_proposals/${id}/reject/`
}

/**
 * Reject the proposal. Persists forever so the pair is never re-proposed.
 */
export const dataCatalogRelationshipProposalsRejectCreate = async (
    projectId: string,
    id: string,
    relationshipRejectApi?: RelationshipRejectApi,
    options?: RequestInit
): Promise<DataCatalogRelationshipProposalApi> => {
    return apiMutator<DataCatalogRelationshipProposalApi>(
        getDataCatalogRelationshipProposalsRejectCreateUrl(projectId, id),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(relationshipRejectApi),
        }
    )
}
