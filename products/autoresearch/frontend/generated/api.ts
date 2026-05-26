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
    AutoresearchSuggestionApi,
    AutoresearchSuggestionsListParams,
    AutoresearchTrainingRunApi,
    AutoresearchTrainingRunsListParams,
    CreateSuggestionApi,
    PaginatedAutoresearchModelListApi,
    PaginatedAutoresearchPipelineListApi,
    PaginatedAutoresearchRunListApi,
    PaginatedAutoresearchSuggestionListApi,
    PaginatedAutoresearchTrainingRunListApi,
    PatchedAutoresearchPipelineCreateApi,
    StartTrainingRequestApi,
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
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/autoresearch/?${stringifiedParams}`
        : `/api/projects/${projectId}/autoresearch/`
}

/**
 * Manage autoresearch prediction pipelines.

A pipeline defines a target event, population, and horizon. The autoresearch
training loop finds the best predictive recipe; the inference workflow scores
users daily and emits autoresearch_prediction events.
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

A pipeline defines a target event, population, and horizon. The autoresearch
training loop finds the best predictive recipe; the inference workflow scores
users daily and emits autoresearch_prediction events.
 */
export const autoresearchCreate = async (
    projectId: string,
    autoresearchPipelineCreateApi: AutoresearchPipelineCreateApi,
    options?: RequestInit
): Promise<AutoresearchPipelineCreateApi> => {
    return apiMutator<AutoresearchPipelineCreateApi>(getAutoresearchCreateUrl(projectId), {
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
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/autoresearch/${pipelineId}/models/?${stringifiedParams}`
        : `/api/projects/${projectId}/autoresearch/${pipelineId}/models/`
}

/**
 * List and retrieve champion/challenger models for a pipeline.

Models are the persisted artifacts produced by training runs. Each model
holds a portable recipe (feature SQL, transforms, model class, params) that
the daily inference workflow compiles to score users.
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

Models are the persisted artifacts produced by training runs. Each model
holds a portable recipe (feature SQL, transforms, model class, params) that
the daily inference workflow compiles to score users.
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
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/autoresearch/${pipelineId}/runs/?${stringifiedParams}`
        : `/api/projects/${projectId}/autoresearch/${pipelineId}/runs/`
}

/**
 * List and retrieve inference, validation, and notebook runs for a pipeline.
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
 * List and retrieve inference, validation, and notebook runs for a pipeline.
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

export const getAutoresearchSuggestionsListUrl = (
    projectId: string,
    pipelineId: string,
    params?: AutoresearchSuggestionsListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/autoresearch/${pipelineId}/suggestions/?${stringifiedParams}`
        : `/api/projects/${projectId}/autoresearch/${pipelineId}/suggestions/`
}

/**
 * List steering suggestions for a pipeline, ordered most recent first. Check 'status' to see which have been picked up or acted on by the agent.
 * @summary List suggestions
 */
export const autoresearchSuggestionsList = async (
    projectId: string,
    pipelineId: string,
    params?: AutoresearchSuggestionsListParams,
    options?: RequestInit
): Promise<PaginatedAutoresearchSuggestionListApi> => {
    return apiMutator<PaginatedAutoresearchSuggestionListApi>(
        getAutoresearchSuggestionsListUrl(projectId, pipelineId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getAutoresearchSuggestionsCreateUrl = (projectId: string, pipelineId: string) => {
    return `/api/projects/${projectId}/autoresearch/${pipelineId}/suggestions/`
}

/**
 * Inject a free-text hypothesis or direction into a running pipeline. The sandbox agent reads queued suggestions at the start of each iteration batch and decides: translate into a concrete iteration ('acted_on'), apply as a search constraint ('picked_up'), or reject with rationale ('dismissed'). Use priority='try_next' to instruct the agent to act on this before autonomous iterations; 'consider' is advisory. Check 'agent_response' after the next training run to see how the suggestion was interpreted.
 * @summary Submit a suggestion
 */
export const autoresearchSuggestionsCreate = async (
    projectId: string,
    pipelineId: string,
    createSuggestionApi: CreateSuggestionApi,
    options?: RequestInit
): Promise<AutoresearchSuggestionApi> => {
    return apiMutator<AutoresearchSuggestionApi>(getAutoresearchSuggestionsCreateUrl(projectId, pipelineId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(createSuggestionApi),
    })
}

export const getAutoresearchSuggestionsRetrieveUrl = (projectId: string, pipelineId: string, id: string) => {
    return `/api/projects/${projectId}/autoresearch/${pipelineId}/suggestions/${id}/`
}

/**
 * Get details for a specific suggestion including its status and agent_response.
 * @summary Get suggestion
 */
export const autoresearchSuggestionsRetrieve = async (
    projectId: string,
    pipelineId: string,
    id: string,
    options?: RequestInit
): Promise<AutoresearchSuggestionApi> => {
    return apiMutator<AutoresearchSuggestionApi>(getAutoresearchSuggestionsRetrieveUrl(projectId, pipelineId, id), {
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
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/autoresearch/${pipelineId}/training_runs/?${stringifiedParams}`
        : `/api/projects/${projectId}/autoresearch/${pipelineId}/training_runs/`
}

/**
 * List and retrieve training runs for a pipeline.
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

A pipeline defines a target event, population, and horizon. The autoresearch
training loop finds the best predictive recipe; the inference workflow scores
users daily and emits autoresearch_prediction events.
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

A pipeline defines a target event, population, and horizon. The autoresearch
training loop finds the best predictive recipe; the inference workflow scores
users daily and emits autoresearch_prediction events.
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

A pipeline defines a target event, population, and horizon. The autoresearch
training loop finds the best predictive recipe; the inference workflow scores
users daily and emits autoresearch_prediction events.
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

A pipeline defines a target event, population, and horizon. The autoresearch
training loop finds the best predictive recipe; the inference workflow scores
users daily and emits autoresearch_prediction events.
 */
export const autoresearchDestroy = async (projectId: string, id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getAutoresearchDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getAutoresearchArchiveCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/autoresearch/${id}/archive/`
}

/**
 * Soft-delete a pipeline. Stops daily scoring and training. Predictions and metrics are preserved.
 * @summary Archive a pipeline
 */
export const autoresearchArchiveCreate = async (
    projectId: string,
    id: string,
    autoresearchPipelineApi: NonReadonly<AutoresearchPipelineApi>,
    options?: RequestInit
): Promise<AutoresearchPipelineApi> => {
    return apiMutator<AutoresearchPipelineApi>(getAutoresearchArchiveCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(autoresearchPipelineApi),
    })
}

export const getAutoresearchPauseCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/autoresearch/${id}/pause/`
}

/**
 * Pause daily scoring and training. The pipeline can be resumed later.
 * @summary Pause a pipeline
 */
export const autoresearchPauseCreate = async (
    projectId: string,
    id: string,
    autoresearchPipelineApi: NonReadonly<AutoresearchPipelineApi>,
    options?: RequestInit
): Promise<AutoresearchPipelineApi> => {
    return apiMutator<AutoresearchPipelineApi>(getAutoresearchPauseCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(autoresearchPipelineApi),
    })
}

export const getAutoresearchResumeCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/autoresearch/${id}/resume/`
}

/**
 * Resume a paused pipeline. Daily scoring and training will restart on the next cadence tick.
 * @summary Resume a pipeline
 */
export const autoresearchResumeCreate = async (
    projectId: string,
    id: string,
    autoresearchPipelineApi: NonReadonly<AutoresearchPipelineApi>,
    options?: RequestInit
): Promise<AutoresearchPipelineApi> => {
    return apiMutator<AutoresearchPipelineApi>(getAutoresearchResumeCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(autoresearchPipelineApi),
    })
}

export const getAutoresearchScoreCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/autoresearch/${id}/score/`
}

/**
 * Score the inference population using the champion model and emit autoresearch_prediction events for each scored user. Updates the predicted_p_<target> person property. In production this is triggered by the daily Temporal inference workflow.
 * @summary Run inference (score users)
 */
export const autoresearchScoreCreate = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<AutoresearchRunApi> => {
    return apiMutator<AutoresearchRunApi>(getAutoresearchScoreCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
    })
}

export const getAutoresearchTrainCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/autoresearch/${id}/train/`
}

/**
 * Trigger a training run for this pipeline. In production this creates a Task/TaskRun sandbox and starts the autoresearch loop. In the stub implementation it synchronously creates a hand-authored champion recipe and marks the run as completed.
 * @summary Start a training run
 */
export const autoresearchTrainCreate = async (
    projectId: string,
    id: string,
    startTrainingRequestApi?: StartTrainingRequestApi,
    options?: RequestInit
): Promise<AutoresearchTrainingRunApi> => {
    return apiMutator<AutoresearchTrainingRunApi>(getAutoresearchTrainCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(startTrainingRequestApi),
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
    validatePipelineRequestApi: ValidatePipelineRequestApi,
    options?: RequestInit
): Promise<ValidatePipelineResponseApi> => {
    return apiMutator<ValidatePipelineResponseApi>(getAutoresearchValidateCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(validatePipelineRequestApi),
    })
}
