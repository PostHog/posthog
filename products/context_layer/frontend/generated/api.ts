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
    CommitBundleApi,
    ContextLayerPagesRetrieveParams,
    ContextLayerStatusApi,
    WikiExportApi,
    WikiPageApi,
    WikiPageWriteApi,
    WikiTreeApi,
} from './api.schemas'

export const getContextLayerCommitsCreateUrl = (organizationId: string) => {
    return `/api/organizations/${organizationId}/context_layer/commits/`
}

/**
 * The organization's context wiki: a git repo of Markdown pages hosted by PostHog.
 * @summary Land agent commits from a git bundle
 */
export const contextLayerCommitsCreate = async (
    organizationId: string,
    commitBundleApi: CommitBundleApi,
    options?: RequestInit
): Promise<ContextLayerStatusApi> => {
    const formData = new FormData()
    formData.append(`bundle`, commitBundleApi.bundle)

    return apiMutator<ContextLayerStatusApi>(getContextLayerCommitsCreateUrl(organizationId), {
        ...options,
        method: 'POST',
        body: formData,
    })
}

export const getContextLayerEnableCreateUrl = (organizationId: string) => {
    return `/api/organizations/${organizationId}/context_layer/enable/`
}

/**
 * Create the organization's wiki with the default structure and import existing channel CONTEXT.md documents once. Idempotent.
 * @summary Enable the context layer
 */
export const contextLayerEnableCreate = async (
    organizationId: string,
    options?: RequestInit
): Promise<ContextLayerStatusApi> => {
    return apiMutator<ContextLayerStatusApi>(getContextLayerEnableCreateUrl(organizationId), {
        ...options,
        method: 'POST',
    })
}

export const getContextLayerExportRetrieveUrl = (organizationId: string) => {
    return `/api/organizations/${organizationId}/context_layer/export/`
}

/**
 * A short-lived download URL for the wiki's current bundle: the whole repo and its history, one file, standard git.
 * @summary Export the wiki
 */
export const contextLayerExportRetrieve = async (
    organizationId: string,
    options?: RequestInit
): Promise<WikiExportApi> => {
    return apiMutator<WikiExportApi>(getContextLayerExportRetrieveUrl(organizationId), {
        ...options,
        method: 'GET',
    })
}

export const getContextLayerPagesRetrieveUrl = (organizationId: string, params: ContextLayerPagesRetrieveParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/organizations/${organizationId}/context_layer/pages/?${stringifiedParams}`
        : `/api/organizations/${organizationId}/context_layer/pages/`
}

/**
 * The organization's context wiki: a git repo of Markdown pages hosted by PostHog.
 * @summary Read a wiki page
 */
export const contextLayerPagesRetrieve = async (
    organizationId: string,
    params: ContextLayerPagesRetrieveParams,
    options?: RequestInit
): Promise<WikiPageApi> => {
    return apiMutator<WikiPageApi>(getContextLayerPagesRetrieveUrl(organizationId, params), {
        ...options,
        method: 'GET',
    })
}

export const getContextLayerPagesUpdateUrl = (organizationId: string) => {
    return `/api/organizations/${organizationId}/context_layer/pages/`
}

/**
 * The organization's context wiki: a git repo of Markdown pages hosted by PostHog.
 * @summary Create or replace a wiki page
 */
export const contextLayerPagesUpdate = async (
    organizationId: string,
    wikiPageWriteApi: WikiPageWriteApi,
    options?: RequestInit
): Promise<ContextLayerStatusApi> => {
    return apiMutator<ContextLayerStatusApi>(getContextLayerPagesUpdateUrl(organizationId), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(wikiPageWriteApi),
    })
}

export const getContextLayerStatusRetrieveUrl = (organizationId: string) => {
    return `/api/organizations/${organizationId}/context_layer/status/`
}

/**
 * The organization's context wiki: a git repo of Markdown pages hosted by PostHog.
 * @summary Get the wiki head
 */
export const contextLayerStatusRetrieve = async (
    organizationId: string,
    options?: RequestInit
): Promise<ContextLayerStatusApi> => {
    return apiMutator<ContextLayerStatusApi>(getContextLayerStatusRetrieveUrl(organizationId), {
        ...options,
        method: 'GET',
    })
}

export const getContextLayerTreeRetrieveUrl = (organizationId: string) => {
    return `/api/organizations/${organizationId}/context_layer/tree/`
}

/**
 * The organization's context wiki: a git repo of Markdown pages hosted by PostHog.
 * @summary List wiki pages
 */
export const contextLayerTreeRetrieve = async (organizationId: string, options?: RequestInit): Promise<WikiTreeApi> => {
    return apiMutator<WikiTreeApi>(getContextLayerTreeRetrieveUrl(organizationId), {
        ...options,
        method: 'GET',
    })
}
