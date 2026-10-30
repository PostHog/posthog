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
    BetsActivityApi,
    BetsDetailApi,
    BetsGuardrailOptionApi,
    BetsGuardrailRequestApi,
    BetsIdeaApi,
    BetsMeasureRequestApi,
    BetsMeasureSearchApi,
    BetsMetricApi,
    BetsMetricPreviewRetrieveParams,
    BetsOverviewApi,
    BetsSettingsApi,
    BetsStatusApi,
    BetsWorkActionApi,
    BetsWriteApi,
    PatchedBetsSettingsWriteApi,
    PatchedBetsWriteApi,
} from './api.schemas'

export const getBetsListUrl = (projectId: string) => {
    return `/api/projects/${projectId}/bets/`
}

export const betsList = async (projectId: string, options?: RequestInit): Promise<BetsOverviewApi> => {
    return apiMutator<BetsOverviewApi>(getBetsListUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getBetsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/bets/`
}

export const betsCreate = async (
    projectId: string,
    betsWriteApi: BetsWriteApi,
    options?: RequestInit
): Promise<BetsDetailApi> => {
    return apiMutator<BetsDetailApi>(getBetsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(betsWriteApi),
    })
}

export const getBetsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/bets/${id}/`
}

export const betsRetrieve = async (projectId: string, id: string, options?: RequestInit): Promise<BetsDetailApi> => {
    return apiMutator<BetsDetailApi>(getBetsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getBetsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/bets/${id}/`
}

export const betsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedBetsWriteApi?: PatchedBetsWriteApi,
    options?: RequestInit
): Promise<BetsDetailApi> => {
    return apiMutator<BetsDetailApi>(getBetsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedBetsWriteApi),
    })
}

export const getBetsActivityListUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/bets/${id}/activity/`
}

export const betsActivityList = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<BetsActivityApi[]> => {
    return apiMutator<BetsActivityApi[]>(getBetsActivityListUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getBetsIdeasCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/bets/${id}/ideas/`
}

export const betsIdeasCreate = async (
    projectId: string,
    id: string,
    betsIdeaApi: BetsIdeaApi,
    options?: RequestInit
): Promise<BetsDetailApi> => {
    return apiMutator<BetsDetailApi>(getBetsIdeasCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(betsIdeaApi),
    })
}

export const getBetsStatusCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/bets/${id}/status/`
}

export const betsStatusCreate = async (
    projectId: string,
    id: string,
    betsStatusApi: BetsStatusApi,
    options?: RequestInit
): Promise<BetsDetailApi> => {
    return apiMutator<BetsDetailApi>(getBetsStatusCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(betsStatusApi),
    })
}

export const getBetsWorkCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/bets/${id}/work/`
}

export const betsWorkCreate = async (
    projectId: string,
    id: string,
    betsWorkActionApi: BetsWorkActionApi,
    options?: RequestInit
): Promise<BetsDetailApi> => {
    return apiMutator<BetsDetailApi>(getBetsWorkCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(betsWorkActionApi),
    })
}

export const getBetsGuardrailsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/bets/guardrails/`
}

export const betsGuardrailsCreate = async (
    projectId: string,
    betsGuardrailRequestApi: BetsGuardrailRequestApi,
    options?: RequestInit
): Promise<BetsGuardrailOptionApi[]> => {
    return apiMutator<BetsGuardrailOptionApi[]>(getBetsGuardrailsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(betsGuardrailRequestApi),
    })
}

export const getBetsMeasuresCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/bets/measures/`
}

export const betsMeasuresCreate = async (
    projectId: string,
    betsMeasureRequestApi: BetsMeasureRequestApi,
    options?: RequestInit
): Promise<BetsMeasureSearchApi> => {
    return apiMutator<BetsMeasureSearchApi>(getBetsMeasuresCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(betsMeasureRequestApi),
    })
}

export const getBetsMetricPreviewRetrieveUrl = (projectId: string, params: BetsMetricPreviewRetrieveParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/bets/metric_preview/?${stringifiedParams}`
        : `/api/projects/${projectId}/bets/metric_preview/`
}

export const betsMetricPreviewRetrieve = async (
    projectId: string,
    params: BetsMetricPreviewRetrieveParams,
    options?: RequestInit
): Promise<BetsMetricApi> => {
    return apiMutator<BetsMetricApi>(getBetsMetricPreviewRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getBetsSettingsRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/bets/settings/`
}

export const betsSettingsRetrieve = async (projectId: string, options?: RequestInit): Promise<BetsSettingsApi> => {
    return apiMutator<BetsSettingsApi>(getBetsSettingsRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getBetsSettingsPartialUpdateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/bets/settings/`
}

export const betsSettingsPartialUpdate = async (
    projectId: string,
    patchedBetsSettingsWriteApi?: PatchedBetsSettingsWriteApi,
    options?: RequestInit
): Promise<BetsSettingsApi> => {
    return apiMutator<BetsSettingsApi>(getBetsSettingsPartialUpdateUrl(projectId), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedBetsSettingsWriteApi),
    })
}
