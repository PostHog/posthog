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
    AutoresearchTemplatesListParams,
    AutoresearchTrainingRunApi,
    AutoresearchTrainingRunsListParams,
    PaginatedAutoresearchModelListApi,
    PaginatedAutoresearchPipelineListApi,
    PaginatedAutoresearchRunListApi,
    PaginatedAutoresearchTrainingRunListApi,
    PaginatedTemplateInfoListApi,
    PatchedAutoresearchPipelineCreateApi,
    ResolveTemplateRequestApi,
    ResolvedTemplateApi,
    ValidatePipelineRequestApi,
    ValidatePipelineResponseApi,
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
 * List, retrieve, open, record iterations into, and complete training runs for a pipeline.
 *
 * The write endpoints let an external (bring-your-own) agent or a scheduled job drive a
 * training run directly — recording each iteration as it completes rather than via a single
 * terminal sandbox output. Recipe validation and champion promotion stay server-side.
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

export const getAutoresearchTrainingRunsCreateUrl = (projectId: string, pipelineId: string) => {
    return `/api/projects/${projectId}/autoresearch/${pipelineId}/training_runs/`
}

/**
 * List, retrieve, open, record iterations into, and complete training runs for a pipeline.
 *
 * The write endpoints let an external (bring-your-own) agent or a scheduled job drive a
 * training run directly — recording each iteration as it completes rather than via a single
 * terminal sandbox output. Recipe validation and champion promotion stay server-side.
 */
export const autoresearchTrainingRunsCreate = async (
    projectId: string,
    pipelineId: string,
    autoresearchTrainingRunApi: NonReadonly<AutoresearchTrainingRunApi>,
    options?: RequestInit
): Promise<AutoresearchTrainingRunApi> => {
    return apiMutator<AutoresearchTrainingRunApi>(getAutoresearchTrainingRunsCreateUrl(projectId, pipelineId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(autoresearchTrainingRunApi),
    })
}

export const getAutoresearchTrainingRunsRetrieveUrl = (projectId: string, pipelineId: string, id: string) => {
    return `/api/projects/${projectId}/autoresearch/${pipelineId}/training_runs/${id}/`
}

/**
 * List, retrieve, open, record iterations into, and complete training runs for a pipeline.
 *
 * The write endpoints let an external (bring-your-own) agent or a scheduled job drive a
 * training run directly — recording each iteration as it completes rather than via a single
 * terminal sandbox output. Recipe validation and champion promotion stay server-side.
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
