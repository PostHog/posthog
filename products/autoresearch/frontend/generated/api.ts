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
    AutoresearchListParams,
    AutoresearchPipelineApi,
    AutoresearchPipelineCreateApi,
    AutoresearchTemplatesListParams,
    PaginatedAutoresearchPipelineListApi,
    PaginatedTemplateInfoListApi,
    PatchedAutoresearchPipelineCreateApi,
    ResolveTemplateRequestApi,
    ResolvedTemplateApi,
    ValidatePipelineRequestApi,
    ValidatePipelineResponseApi,
} from './api.schemas'

export const getAutoresearchListUrl = (projectId: string, params?: AutoresearchListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/autoresearch/?${stringifiedParams}`
        : `/api/projects/${projectId}/autoresearch/`
}

/**
 * Manage autoresearch prediction pipelines.
 *
 * A pipeline defines a target event, population, and horizon. The autoresearch
 * training loop finds the best predictive recipe; the inference workflow scores
 * users daily and emits autoresearch_prediction events.
 */
export const autoresearchList = async (
    projectId: string,
    params?: AutoresearchListParams,
    options?: RequestInit
): Promise<PaginatedAutoresearchPipelineListApi> => {
    return apiMutator<PaginatedAutoresearchPipelineListApi>(getAutoresearchListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getAutoresearchCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/autoresearch/`
}

/**
 * Manage autoresearch prediction pipelines.
 *
 * A pipeline defines a target event, population, and horizon. The autoresearch
 * training loop finds the best predictive recipe; the inference workflow scores
 * users daily and emits autoresearch_prediction events.
 */
export const autoresearchCreate = async (
    projectId: string,
    autoresearchPipelineCreateApi: AutoresearchPipelineCreateApi,
    options?: RequestInit
): Promise<AutoresearchPipelineApi> => {
    return apiMutator<AutoresearchPipelineApi>(getAutoresearchCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(autoresearchPipelineCreateApi),
    })
}

export const getAutoresearchRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/autoresearch/${id}/`
}

/**
 * Manage autoresearch prediction pipelines.
 *
 * A pipeline defines a target event, population, and horizon. The autoresearch
 * training loop finds the best predictive recipe; the inference workflow scores
 * users daily and emits autoresearch_prediction events.
 */
export const autoresearchRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<AutoresearchPipelineApi> => {
    return apiMutator<AutoresearchPipelineApi>(getAutoresearchRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getAutoresearchUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/autoresearch/${id}/`
}

/**
 * Manage autoresearch prediction pipelines.
 *
 * A pipeline defines a target event, population, and horizon. The autoresearch
 * training loop finds the best predictive recipe; the inference workflow scores
 * users daily and emits autoresearch_prediction events.
 */
export const autoresearchUpdate = async (
    projectId: string,
    id: string,
    autoresearchPipelineCreateApi: AutoresearchPipelineCreateApi,
    options?: RequestInit
): Promise<AutoresearchPipelineCreateApi> => {
    return apiMutator<AutoresearchPipelineCreateApi>(getAutoresearchUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(autoresearchPipelineCreateApi),
    })
}

export const getAutoresearchPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/autoresearch/${id}/`
}

/**
 * Manage autoresearch prediction pipelines.
 *
 * A pipeline defines a target event, population, and horizon. The autoresearch
 * training loop finds the best predictive recipe; the inference workflow scores
 * users daily and emits autoresearch_prediction events.
 */
export const autoresearchPartialUpdate = async (
    projectId: string,
    id: string,
    patchedAutoresearchPipelineCreateApi?: PatchedAutoresearchPipelineCreateApi,
    options?: RequestInit
): Promise<AutoresearchPipelineCreateApi> => {
    return apiMutator<AutoresearchPipelineCreateApi>(getAutoresearchPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedAutoresearchPipelineCreateApi),
    })
}

export const getAutoresearchDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/autoresearch/${id}/`
}

/**
 * Manage autoresearch prediction pipelines.
 *
 * A pipeline defines a target event, population, and horizon. The autoresearch
 * training loop finds the best predictive recipe; the inference workflow scores
 * users daily and emits autoresearch_prediction events.
 */
export const autoresearchDestroy = async (projectId: string, id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getAutoresearchDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getAutoresearchResolveTemplateCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/autoresearch/resolve-template/`
}

/**
 * Resolve a template key and optional overrides into a concrete pipeline config. For activity-based templates ('likely_active_soon', 'at_risk_of_inactivity', 'return_after_first_use'), the target event is auto-resolved from your event schema — check resolved_activity_event and activity_event_alternatives, then override if needed. For 'feature_adoption' and 'repeat_key_behavior', supply target_event. After resolving, call autoresearch-validate-create to check volume and warnings, then autoresearch-create to create the pipeline.
 * @summary Resolve a template
 */
export const autoresearchResolveTemplateCreate = async (
    projectId: string,
    resolveTemplateRequestApi: ResolveTemplateRequestApi,
    options?: RequestInit
): Promise<ResolvedTemplateApi> => {
    return apiMutator<ResolvedTemplateApi>(getAutoresearchResolveTemplateCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(resolveTemplateRequestApi),
    })
}

export const getAutoresearchTemplatesListUrl = (projectId: string, params?: AutoresearchTemplatesListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/autoresearch/templates/?${stringifiedParams}`
        : `/api/projects/${projectId}/autoresearch/templates/`
}

/**
 * Return all built-in autoresearch prediction templates. Each entry describes what the template predicts, its default horizon and prediction mode, and whether it requires you to supply a target_event. After choosing a template, call autoresearch-resolve-template-create to get a fully resolved pipeline config ready to pass to autoresearch-create.
 * @summary List available templates
 */
export const autoresearchTemplatesList = async (
    projectId: string,
    params?: AutoresearchTemplatesListParams,
    options?: RequestInit
): Promise<PaginatedTemplateInfoListApi> => {
    return apiMutator<PaginatedTemplateInfoListApi>(getAutoresearchTemplatesListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getAutoresearchValidateCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/autoresearch/validate/`
}

/**
 * Validate a proposed pipeline's target event and population before creating it. Returns volume estimates, base rate, and any warnings. Warnings with severity='error' must be resolved before creation can proceed. Call this before autoresearch-create.
 * @summary Validate a pipeline definition
 */
export const autoresearchValidateCreate = async (
    projectId: string,
    validatePipelineRequestApi?: ValidatePipelineRequestApi,
    options?: RequestInit
): Promise<ValidatePipelineResponseApi> => {
    return apiMutator<ValidatePipelineResponseApi>(getAutoresearchValidateCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(validatePipelineRequestApi),
    })
}
