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
    AutoresearchModelApi,
    AutoresearchModelsListParams,
    AutoresearchPipelineApi,
    AutoresearchPipelineCreateApi,
    AutoresearchRunApi,
    AutoresearchRunsListParams,
    AutoresearchTrainingRunApi,
    AutoresearchTrainingRunsListParams,
    PaginatedAutoresearchModelListApi,
    PaginatedAutoresearchPipelineListApi,
    PaginatedAutoresearchRunListApi,
    PaginatedAutoresearchTrainingRunListApi,
    PatchedAutoresearchPipelineCreateApi,
    ResolveTemplateRequestApi,
    ResolvedTemplateApi,
    TemplateInfoApi,
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

export const getAutoresearchModelsListUrl = (
    projectId: string,
    pipelineId: string,
    params?: AutoresearchModelsListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/autoresearch/${pipelineId}/models/?${stringifiedParams}`
        : `/api/projects/${projectId}/autoresearch/${pipelineId}/models/`
}

/**
 * List and retrieve champion/challenger models for a pipeline.
 *
 * Models are the persisted artifacts produced by training runs. Each model
 * holds a portable recipe (feature SQL, transforms, model class, params) that
 * the daily inference workflow compiles to score users.
 */
export const autoresearchModelsList = async (
    projectId: string,
    pipelineId: string,
    params?: AutoresearchModelsListParams,
    options?: RequestInit
): Promise<PaginatedAutoresearchModelListApi> => {
    return apiMutator<PaginatedAutoresearchModelListApi>(getAutoresearchModelsListUrl(projectId, pipelineId, params), {
        ...options,
        method: 'GET',
    })
}

export const getAutoresearchModelsRetrieveUrl = (projectId: string, pipelineId: string, id: string) => {
    return `/api/projects/${projectId}/autoresearch/${pipelineId}/models/${id}/`
}

/**
 * List and retrieve champion/challenger models for a pipeline.
 *
 * Models are the persisted artifacts produced by training runs. Each model
 * holds a portable recipe (feature SQL, transforms, model class, params) that
 * the daily inference workflow compiles to score users.
 */
export const autoresearchModelsRetrieve = async (
    projectId: string,
    pipelineId: string,
    id: string,
    options?: RequestInit
): Promise<AutoresearchModelApi> => {
    return apiMutator<AutoresearchModelApi>(getAutoresearchModelsRetrieveUrl(projectId, pipelineId, id), {
        ...options,
        method: 'GET',
    })
}

export const getAutoresearchRunsListUrl = (
    projectId: string,
    pipelineId: string,
    params?: AutoresearchRunsListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/autoresearch/${pipelineId}/runs/?${stringifiedParams}`
        : `/api/projects/${projectId}/autoresearch/${pipelineId}/runs/`
}

/**
 * List and retrieve inference and validation runs for a pipeline.
 */
export const autoresearchRunsList = async (
    projectId: string,
    pipelineId: string,
    params?: AutoresearchRunsListParams,
    options?: RequestInit
): Promise<PaginatedAutoresearchRunListApi> => {
    return apiMutator<PaginatedAutoresearchRunListApi>(getAutoresearchRunsListUrl(projectId, pipelineId, params), {
        ...options,
        method: 'GET',
    })
}

export const getAutoresearchRunsRetrieveUrl = (projectId: string, pipelineId: string, id: string) => {
    return `/api/projects/${projectId}/autoresearch/${pipelineId}/runs/${id}/`
}

/**
 * List and retrieve inference and validation runs for a pipeline.
 */
export const autoresearchRunsRetrieve = async (
    projectId: string,
    pipelineId: string,
    id: string,
    options?: RequestInit
): Promise<AutoresearchRunApi> => {
    return apiMutator<AutoresearchRunApi>(getAutoresearchRunsRetrieveUrl(projectId, pipelineId, id), {
        ...options,
        method: 'GET',
    })
}

export const getAutoresearchTrainingRunsListUrl = (
    projectId: string,
    pipelineId: string,
    params?: AutoresearchTrainingRunsListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/autoresearch/${pipelineId}/training_runs/?${stringifiedParams}`
        : `/api/projects/${projectId}/autoresearch/${pipelineId}/training_runs/`
}

/**
 * List and retrieve training runs for a pipeline.
 *
 * A training run records the agent's search for a model: each iteration's recipe and holdout
 * score, and the summary of the run once it completes.
 */
export const autoresearchTrainingRunsList = async (
    projectId: string,
    pipelineId: string,
    params?: AutoresearchTrainingRunsListParams,
    options?: RequestInit
): Promise<PaginatedAutoresearchTrainingRunListApi> => {
    return apiMutator<PaginatedAutoresearchTrainingRunListApi>(
        getAutoresearchTrainingRunsListUrl(projectId, pipelineId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getAutoresearchTrainingRunsRetrieveUrl = (projectId: string, pipelineId: string, id: string) => {
    return `/api/projects/${projectId}/autoresearch/${pipelineId}/training_runs/${id}/`
}

/**
 * List and retrieve training runs for a pipeline.
 *
 * A training run records the agent's search for a model: each iteration's recipe and holdout
 * score, and the summary of the run once it completes.
 */
export const autoresearchTrainingRunsRetrieve = async (
    projectId: string,
    pipelineId: string,
    id: string,
    options?: RequestInit
): Promise<AutoresearchTrainingRunApi> => {
    return apiMutator<AutoresearchTrainingRunApi>(getAutoresearchTrainingRunsRetrieveUrl(projectId, pipelineId, id), {
        ...options,
        method: 'GET',
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

export const getAutoresearchTemplatesListUrl = (projectId: string) => {
    return `/api/projects/${projectId}/autoresearch/templates/`
}

/**
 * Return all built-in autoresearch prediction templates. Each entry describes what the template predicts, its default horizon and prediction mode, and whether it requires you to supply a target_event. After choosing a template, call autoresearch-resolve-template-create to get a fully resolved pipeline config ready to pass to autoresearch-create.
 * @summary List available templates
 */
export const autoresearchTemplatesList = async (
    projectId: string,
    options?: RequestInit
): Promise<TemplateInfoApi[]> => {
    return apiMutator<TemplateInfoApi[]>(getAutoresearchTemplatesListUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getAutoresearchValidateCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/autoresearch/validate/`
}

/**
 * Validate a proposed pipeline's target event and population before creating it. Returns volume estimates, base rate, and any warnings. Creation does not enforce the result: 'population_too_large' and 'horizon_exceeds_lookback' mean a training run would fail, and the other 'error' codes mean the data is too thin for a reliable model. Call this before autoresearch-create.
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
