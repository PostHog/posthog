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
    CloudAgentCatalogApi,
    CloudAgentEstimateApi,
    CloudAgentPresetApi,
    CloudAgentPresetCreateApi,
    CloudAgentRunApi,
    CloudAgentRunCreateApi,
    CloudAgentRunEventsApi,
    CloudAgentRunMessageApi,
    CloudAgentRunMessageResponseApi,
    CloudAgentRunUsageApi,
    CloudAgentSettingsApi,
    CloudAgentUsageSummaryApi,
    CloudAgentsEstimateRetrieveParams,
    CloudAgentsPresetsListParams,
    CloudAgentsRunsEventsRetrieveParams,
    CloudAgentsRunsListParams,
    CloudAgentsUsageRetrieveParams,
    PaginatedCloudAgentPresetListApi,
    PaginatedCloudAgentRunListApi,
    PatchedCloudAgentPresetUpdateApi,
    PatchedCloudAgentSettingsUpdateApi,
} from './api.schemas'

export const getCloudAgentsCatalogRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/cloud_agents/catalog/`
}

/**
 * The sizes, models and inference modes that a run can use, with the prices and the limits.
 * @summary Retrieve the cloud agents catalog
 */
export const cloudAgentsCatalogRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<CloudAgentCatalogApi> => {
    return apiMutator<CloudAgentCatalogApi>(getCloudAgentsCatalogRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getCloudAgentsEstimateRetrieveUrl = (projectId: string, params: CloudAgentsEstimateRetrieveParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/cloud_agents/estimate/?${stringifiedParams}`
        : `/api/projects/${projectId}/cloud_agents/estimate/`
}

/**
 * The compute cost of a sandbox of one size for a number of minutes. Model usage is not included.
 * @summary Estimate the compute cost of a run
 */
export const cloudAgentsEstimateRetrieve = async (
    projectId: string,
    params: CloudAgentsEstimateRetrieveParams,
    options?: RequestInit
): Promise<CloudAgentEstimateApi> => {
    return apiMutator<CloudAgentEstimateApi>(getCloudAgentsEstimateRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getCloudAgentsPresetsListUrl = (projectId: string, params?: CloudAgentsPresetsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/cloud_agents/presets/?${stringifiedParams}`
        : `/api/projects/${projectId}/cloud_agents/presets/`
}

/**
 * Base for every cloud_agents viewset: the scope object, the feature flag, and the error mapping.
 * @summary List presets
 */
export const cloudAgentsPresetsList = async (
    projectId: string,
    params?: CloudAgentsPresetsListParams,
    options?: RequestInit
): Promise<PaginatedCloudAgentPresetListApi> => {
    return apiMutator<PaginatedCloudAgentPresetListApi>(getCloudAgentsPresetsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getCloudAgentsPresetsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/cloud_agents/presets/`
}

/**
 * A preset is a named set of run defaults. A run that names a preset needs only a prompt.
 * @summary Create a preset
 */
export const cloudAgentsPresetsCreate = async (
    projectId: string,
    cloudAgentPresetCreateApi: CloudAgentPresetCreateApi,
    options?: RequestInit
): Promise<CloudAgentPresetApi> => {
    return apiMutator<CloudAgentPresetApi>(getCloudAgentsPresetsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(cloudAgentPresetCreateApi),
    })
}

export const getCloudAgentsPresetsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/cloud_agents/presets/${id}/`
}

/**
 * Base for every cloud_agents viewset: the scope object, the feature flag, and the error mapping.
 * @summary Retrieve a preset
 */
export const cloudAgentsPresetsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<CloudAgentPresetApi> => {
    return apiMutator<CloudAgentPresetApi>(getCloudAgentsPresetsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getCloudAgentsPresetsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/cloud_agents/presets/${id}/`
}

/**
 * Only the fields in the request change. A null value clears a default.
 * @summary Update a preset
 */
export const cloudAgentsPresetsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedCloudAgentPresetUpdateApi?: PatchedCloudAgentPresetUpdateApi,
    options?: RequestInit
): Promise<CloudAgentPresetApi> => {
    return apiMutator<CloudAgentPresetApi>(getCloudAgentsPresetsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedCloudAgentPresetUpdateApi),
    })
}

export const getCloudAgentsPresetsDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/cloud_agents/presets/${id}/`
}

/**
 * Runs that used the preset keep their configuration. The name becomes free.
 * @summary Delete a preset
 */
export const cloudAgentsPresetsDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getCloudAgentsPresetsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getCloudAgentsRunsListUrl = (projectId: string, params?: CloudAgentsRunsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/cloud_agents/runs/?${stringifiedParams}`
        : `/api/projects/${projectId}/cloud_agents/runs/`
}

/**
 * The runs of the project, newest first.
 * @summary List runs
 */
export const cloudAgentsRunsList = async (
    projectId: string,
    params?: CloudAgentsRunsListParams,
    options?: RequestInit
): Promise<PaginatedCloudAgentRunListApi> => {
    return apiMutator<PaginatedCloudAgentRunListApi>(getCloudAgentsRunsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getCloudAgentsRunsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/cloud_agents/runs/`
}

/**
 * Starts a sandbox with a coding agent that works on the prompt in the repository. The response returns at once with a `queued` run. Read the run or stream its events to follow it. Send the same `Idempotency-Key` header again to get the same run and not a second one.
 * @summary Start a run
 */
export const cloudAgentsRunsCreate = async (
    projectId: string,
    cloudAgentRunCreateApi: CloudAgentRunCreateApi,
    options?: RequestInit
): Promise<CloudAgentRunApi> => {
    return apiMutator<CloudAgentRunApi>(getCloudAgentsRunsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(cloudAgentRunCreateApi),
    })
}

export const getCloudAgentsRunsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/cloud_agents/runs/${id}/`
}

/**
 * Base for every cloud_agents viewset: the scope object, the feature flag, and the error mapping.
 * @summary Retrieve a run
 */
export const cloudAgentsRunsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<CloudAgentRunApi> => {
    return apiMutator<CloudAgentRunApi>(getCloudAgentsRunsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getCloudAgentsRunsCancelCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/cloud_agents/runs/${id}/cancel/`
}

/**
 * Asks a `queued` or `running` run to stop. The response has status 202 and the run can still be `running` for a short time. It is then `done` with the reason `cancelled`. An `idle` or `done` run has no agent to stop, so it is returned with status 200 and does not change.
 * @summary Cancel a run
 */
export const cloudAgentsRunsCancelCreate = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<CloudAgentRunApi> => {
    return apiMutator<CloudAgentRunApi>(getCloudAgentsRunsCancelCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
    })
}

export const getCloudAgentsRunsEventsRetrieveUrl = (
    projectId: string,
    id: string,
    params?: CloudAgentsRunsEventsRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/cloud_agents/runs/${id}/events/?${stringifiedParams}`
        : `/api/projects/${projectId}/cloud_agents/runs/${id}/events/`
}

/**
 * By default, the response is one JSON object with the stored events of all agent sessions. To follow a live run, send `Accept: text/event-stream`. The response is then a Server-Sent Events stream of the current agent session. Its first frame is `event: run` with the ID, the status and the status reason of the run. `Last-Event-ID` and `start=latest` apply to the stream only. To resume after a disconnect, send the `id` of the last event in the `Last-Event-ID` header.
 *
 * **SDK consumers**: a generated fetch wrapper buffers the stream. Use the JSON default through it, and read the stream with a streaming `fetch` or an `EventSource` client.
 * @summary Read the events of a run
 */
export const cloudAgentsRunsEventsRetrieve = async (
    projectId: string,
    id: string,
    params?: CloudAgentsRunsEventsRetrieveParams,
    options?: RequestInit
): Promise<CloudAgentRunEventsApi | string> => {
    return apiMutator<CloudAgentRunEventsApi | string>(getCloudAgentsRunsEventsRetrieveUrl(projectId, id, params), {
        ...options,
        method: 'GET',
    })
}

export const getCloudAgentsRunsMessagesCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/cloud_agents/runs/${id}/messages/`
}

/**
 * Sends a follow-up message. An agent that is at work gets the message in its current session. An `idle` run starts a new agent session with the message and goes back to `queued`. A `done` run refuses the message with status 409 and the code `run_done`.
 * @summary Send a message to a run
 */
export const cloudAgentsRunsMessagesCreate = async (
    projectId: string,
    id: string,
    cloudAgentRunMessageApi: CloudAgentRunMessageApi,
    options?: RequestInit
): Promise<CloudAgentRunMessageResponseApi> => {
    return apiMutator<CloudAgentRunMessageResponseApi>(getCloudAgentsRunsMessagesCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(cloudAgentRunMessageApi),
    })
}

export const getCloudAgentsRunsUsageRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/cloud_agents/runs/${id}/usage/`
}

/**
 * The cost of the run up to now, and each sandbox that it used.
 * @summary Retrieve the usage of a run
 */
export const cloudAgentsRunsUsageRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<CloudAgentRunUsageApi> => {
    return apiMutator<CloudAgentRunUsageApi>(getCloudAgentsRunsUsageRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getCloudAgentsSettingsRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/cloud_agents/settings/`
}

/**
 * The run defaults and the limits of the project.
 * @summary Retrieve cloud agent settings
 */
export const cloudAgentsSettingsRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<CloudAgentSettingsApi> => {
    return apiMutator<CloudAgentSettingsApi>(getCloudAgentsSettingsRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getCloudAgentsSettingsPartialUpdateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/cloud_agents/settings/`
}

/**
 * Only the fields in the request change. A null value clears a default.
 * @summary Update cloud agent settings
 */
export const cloudAgentsSettingsPartialUpdate = async (
    projectId: string,
    patchedCloudAgentSettingsUpdateApi?: PatchedCloudAgentSettingsUpdateApi,
    options?: RequestInit
): Promise<CloudAgentSettingsApi> => {
    return apiMutator<CloudAgentSettingsApi>(getCloudAgentsSettingsPartialUpdateUrl(projectId), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedCloudAgentSettingsUpdateApi),
    })
}

export const getCloudAgentsUsageRetrieveUrl = (projectId: string, params?: CloudAgentsUsageRetrieveParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/cloud_agents/usage/?${stringifiedParams}`
        : `/api/projects/${projectId}/cloud_agents/usage/`
}

/**
 * Cost and usage totals of the runs created in a date range, for each day or for each preset.
 * @summary Retrieve cloud agents usage
 */
export const cloudAgentsUsageRetrieve = async (
    projectId: string,
    params?: CloudAgentsUsageRetrieveParams,
    options?: RequestInit
): Promise<CloudAgentUsageSummaryApi> => {
    return apiMutator<CloudAgentUsageSummaryApi>(getCloudAgentsUsageRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}
