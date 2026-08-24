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
    ChannelWikiPageApi,
    CommitBundleApi,
    ContextLayerAgentPagesRetrieveParams,
    ContextLayerPagesRetrieveParams,
    ContextLayerStatusApi,
    WikiExportApi,
    WikiHealthReportApi,
    WikiPageApi,
    WikiPageWriteApi,
    WikiTreeApi,
} from './api.schemas'

export const getContextLayerChannelPagesRetrieveUrl = (organizationId: string, channelId: string) => {
    return `/api/organizations/${organizationId}/context_layer/channel-pages/${channelId}/`
}

/**
 * The organization's context wiki: a git repo of Markdown pages hosted by PostHog.
 * @summary Resolve a channel's wiki page
 */
export const contextLayerChannelPagesRetrieve = async (
    organizationId: string,
    channelId: string,
    options?: RequestInit
): Promise<ChannelWikiPageApi> => {
    return apiMutator<ChannelWikiPageApi>(getContextLayerChannelPagesRetrieveUrl(organizationId, channelId), {
        ...options,
        method: 'GET',
    })
}

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
    if (commitBundleApi.summary !== undefined) {
        formData.append(`summary`, commitBundleApi.summary)
    }
    if (commitBundleApi.branch !== undefined && commitBundleApi.branch !== null) {
        formData.append(`branch`, commitBundleApi.branch)
    }

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

export const getContextLayerWikiReportRetrieveUrl = (organizationId: string) => {
    return `/api/organizations/${organizationId}/context_layer/wiki/report/`
}

/**
 * The organization's context wiki: a git repo of Markdown pages hosted by PostHog.
 * @summary Report wiki health findings
 */
export const contextLayerWikiReportRetrieve = async (
    organizationId: string,
    options?: RequestInit
): Promise<WikiHealthReportApi> => {
    return apiMutator<WikiHealthReportApi>(getContextLayerWikiReportRetrieveUrl(organizationId), {
        ...options,
        method: 'GET',
    })
}

export const getContextLayerAgentChannelPagesRetrieveUrl = (projectId: string, channelId: string) => {
    return `/api/projects/${projectId}/context_layer/agent/channel-pages/${channelId}/`
}

/**
 * The channel's page path. When the channel has no page yet, responds with the canonical path to create it at and `exists: false`.
 * @summary Resolve a channel's wiki page
 */
export const contextLayerAgentChannelPagesRetrieve = async (
    projectId: string,
    channelId: string,
    options?: RequestInit
): Promise<ChannelWikiPageApi> => {
    return apiMutator<ChannelWikiPageApi>(getContextLayerAgentChannelPagesRetrieveUrl(projectId, channelId), {
        ...options,
        method: 'GET',
    })
}

export const getContextLayerAgentCommitsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/context_layer/agent/commits/`
}

/**
 * The same organization wiki, reached by an agent run inside a sandbox.
 *
 * This exists as a second, project-nested route because a sandbox run token
 * carries `scoped_teams`, and `APIScopePermission` accepts those only on a
 * project-nested view — on the organization-scoped route above, every sandbox
 * token is refused before it reaches any of this. The wiki is still one repo
 * per organization; the project in the path is how a run token proves which
 * organization it may act for, and is not a scope on the wiki itself.
 * @summary Land agent commits from a git bundle
 */
export const contextLayerAgentCommitsCreate = async (
    projectId: string,
    commitBundleApi: CommitBundleApi,
    options?: RequestInit
): Promise<ContextLayerStatusApi> => {
    const formData = new FormData()
    formData.append(`bundle`, commitBundleApi.bundle)
    if (commitBundleApi.summary !== undefined) {
        formData.append(`summary`, commitBundleApi.summary)
    }
    if (commitBundleApi.branch !== undefined && commitBundleApi.branch !== null) {
        formData.append(`branch`, commitBundleApi.branch)
    }

    return apiMutator<ContextLayerStatusApi>(getContextLayerAgentCommitsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        body: formData,
    })
}

export const getContextLayerAgentPagesRetrieveUrl = (
    projectId: string,
    params: ContextLayerAgentPagesRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/context_layer/agent/pages/?${stringifiedParams}`
        : `/api/projects/${projectId}/context_layer/agent/pages/`
}

/**
 * The same organization wiki, reached by an agent run inside a sandbox.
 *
 * This exists as a second, project-nested route because a sandbox run token
 * carries `scoped_teams`, and `APIScopePermission` accepts those only on a
 * project-nested view — on the organization-scoped route above, every sandbox
 * token is refused before it reaches any of this. The wiki is still one repo
 * per organization; the project in the path is how a run token proves which
 * organization it may act for, and is not a scope on the wiki itself.
 * @summary Read a wiki page
 */
export const contextLayerAgentPagesRetrieve = async (
    projectId: string,
    params: ContextLayerAgentPagesRetrieveParams,
    options?: RequestInit
): Promise<WikiPageApi> => {
    return apiMutator<WikiPageApi>(getContextLayerAgentPagesRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getContextLayerAgentPagesUpdateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/context_layer/agent/pages/`
}

/**
 * The same organization wiki, reached by an agent run inside a sandbox.
 *
 * This exists as a second, project-nested route because a sandbox run token
 * carries `scoped_teams`, and `APIScopePermission` accepts those only on a
 * project-nested view — on the organization-scoped route above, every sandbox
 * token is refused before it reaches any of this. The wiki is still one repo
 * per organization; the project in the path is how a run token proves which
 * organization it may act for, and is not a scope on the wiki itself.
 * @summary Create or replace a wiki page
 */
export const contextLayerAgentPagesUpdate = async (
    projectId: string,
    wikiPageWriteApi: WikiPageWriteApi,
    options?: RequestInit
): Promise<ContextLayerStatusApi> => {
    return apiMutator<ContextLayerStatusApi>(getContextLayerAgentPagesUpdateUrl(projectId), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(wikiPageWriteApi),
    })
}
