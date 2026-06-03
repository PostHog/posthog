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
    ArtifactContentApi,
    ArtifactDeleteResultApi,
    ArtifactListApi,
    ArtifactPathApi,
    ArtifactUploadApi,
    AutoresearchIterationApi,
    AutoresearchListParams,
    AutoresearchModelApi,
    AutoresearchModelsListParams,
    AutoresearchPipelineApi,
    AutoresearchPipelineCreateApi,
    AutoresearchRunApi,
    AutoresearchRunsListParams,
    AutoresearchSuggestionApi,
    AutoresearchSuggestionsListParams,
    AutoresearchTemplatesListParams,
    AutoresearchTrainingRunApi,
    AutoresearchTrainingRunsHistoryRetrieveParams,
    AutoresearchTrainingRunsListParams,
    CompleteTrainingRunApi,
    CreateSuggestionApi,
    MaterializeFeaturesRequestApi,
    MaterializeFeaturesResponseApi,
    OpenTrainingRunApi,
    PaginatedAutoresearchModelListApi,
    PaginatedAutoresearchPipelineListApi,
    PaginatedAutoresearchRunListApi,
    PaginatedAutoresearchSuggestionListApi,
    PaginatedAutoresearchTrainingRunListApi,
    PaginatedTemplateInfoListApi,
    PatchedAutoresearchPipelineCreateApi,
    RecordIterationApi,
    ResolveTemplateRequestApi,
    ResolvedTemplateApi,
    StartTrainingRequestApi,
    StoredArtifactApi,
    TrainingRunHistoryApi,
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
 * List, retrieve, open, record iterations into, and complete training runs for a pipeline.

The write endpoints let an external (bring-your-own) agent or a scheduled job drive a
training run directly — recording each iteration as it completes rather than via a single
terminal sandbox output. Recipe validation and champion promotion stay server-side.
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
 * Open a new training run for a pipeline and return its id. An agent — the in-house sandbox, an external bring-your-own agent, or a scheduled job — then records iterations against this run and finalizes it with the complete endpoint. The run starts in 'running'.
 * @summary Open a training run
 */
export const autoresearchTrainingRunsCreate = async (
    projectId: string,
    pipelineId: string,
    openTrainingRunApi?: OpenTrainingRunApi,
    options?: RequestInit
): Promise<AutoresearchTrainingRunApi> => {
    return apiMutator<AutoresearchTrainingRunApi>(getAutoresearchTrainingRunsCreateUrl(projectId, pipelineId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(openTrainingRunApi),
    })
}

export const getAutoresearchTrainingRunsRetrieveUrl = (projectId: string, pipelineId: string, id: string) => {
    return `/api/projects/${projectId}/autoresearch/${pipelineId}/training_runs/${id}/`
}

/**
 * List, retrieve, open, record iterations into, and complete training runs for a pipeline.

The write endpoints let an external (bring-your-own) agent or a scheduled job drive a
training run directly — recording each iteration as it completes rather than via a single
terminal sandbox output. Recipe validation and champion promotion stay server-side.
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

export const getAutoresearchTrainingRunsArtifactsRetrieveUrl = (projectId: string, pipelineId: string, id: string) => {
    return `/api/projects/${projectId}/autoresearch/${pipelineId}/training_runs/${id}/artifacts/`
}

/**
 * List the files an agent has uploaded for this training run's artifact bundle (train.py, predict.py, features.sql, and any eda/ notebooks).
 * @summary List artifact bundle files
 */
export const autoresearchTrainingRunsArtifactsRetrieve = async (
    projectId: string,
    pipelineId: string,
    id: string,
    options?: RequestInit
): Promise<ArtifactListApi> => {
    return apiMutator<ArtifactListApi>(getAutoresearchTrainingRunsArtifactsRetrieveUrl(projectId, pipelineId, id), {
        ...options,
        method: 'GET',
    })
}

export const getAutoresearchTrainingRunsArtifactsDeleteCreateUrl = (
    projectId: string,
    pipelineId: string,
    id: string
) => {
    return `/api/projects/${projectId}/autoresearch/${pipelineId}/training_runs/${id}/artifacts/delete/`
}

/**
 * Remove one file from this training run's artifact bundle. Idempotent — deleting a missing file is a no-op.
 * @summary Delete an artifact bundle file
 */
export const autoresearchTrainingRunsArtifactsDeleteCreate = async (
    projectId: string,
    pipelineId: string,
    id: string,
    artifactPathApi: ArtifactPathApi,
    options?: RequestInit
): Promise<ArtifactDeleteResultApi> => {
    return apiMutator<ArtifactDeleteResultApi>(
        getAutoresearchTrainingRunsArtifactsDeleteCreateUrl(projectId, pipelineId, id),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(artifactPathApi),
        }
    )
}

export const getAutoresearchTrainingRunsArtifactsGetCreateUrl = (projectId: string, pipelineId: string, id: string) => {
    return `/api/projects/${projectId}/autoresearch/${pipelineId}/training_runs/${id}/artifacts/get/`
}

/**
 * Fetch one file from this training run's artifact bundle, base64-encoded.
 * @summary Get an artifact bundle file
 */
export const autoresearchTrainingRunsArtifactsGetCreate = async (
    projectId: string,
    pipelineId: string,
    id: string,
    artifactPathApi: ArtifactPathApi,
    options?: RequestInit
): Promise<ArtifactContentApi> => {
    return apiMutator<ArtifactContentApi>(getAutoresearchTrainingRunsArtifactsGetCreateUrl(projectId, pipelineId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(artifactPathApi),
    })
}

export const getAutoresearchTrainingRunsArtifactsUploadCreateUrl = (
    projectId: string,
    pipelineId: string,
    id: string
) => {
    return `/api/projects/${projectId}/autoresearch/${pipelineId}/training_runs/${id}/artifacts/upload/`
}

/**
 * Upload one file of this training run's artifact bundle. Send the file contents base64-encoded in content_base64. Re-uploading the same path overwrites it. Use this — not curl/set_output — to author train.py, predict.py, and features.sql.
 * @summary Upload an artifact bundle file
 */
export const autoresearchTrainingRunsArtifactsUploadCreate = async (
    projectId: string,
    pipelineId: string,
    id: string,
    artifactUploadApi: ArtifactUploadApi,
    options?: RequestInit
): Promise<StoredArtifactApi> => {
    return apiMutator<StoredArtifactApi>(
        getAutoresearchTrainingRunsArtifactsUploadCreateUrl(projectId, pipelineId, id),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(artifactUploadApi),
        }
    )
}

export const getAutoresearchTrainingRunsCompleteCreateUrl = (projectId: string, pipelineId: string, id: string) => {
    return `/api/projects/${projectId}/autoresearch/${pipelineId}/training_runs/${id}/complete/`
}

/**
 * Finalize a training run. The backend selects the best iteration (highest holdout score, or the one you name), decides champion vs challenger via the promotion ladder, and persists the model. Agents cannot set the champion directly — promotion is server-side.
 * @summary Complete a training run
 */
export const autoresearchTrainingRunsCompleteCreate = async (
    projectId: string,
    pipelineId: string,
    id: string,
    completeTrainingRunApi?: CompleteTrainingRunApi,
    options?: RequestInit
): Promise<AutoresearchTrainingRunApi> => {
    return apiMutator<AutoresearchTrainingRunApi>(
        getAutoresearchTrainingRunsCompleteCreateUrl(projectId, pipelineId, id),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(completeTrainingRunApi),
        }
    )
}

export const getAutoresearchTrainingRunsIterationsCreateUrl = (projectId: string, pipelineId: string, id: string) => {
    return `/api/projects/${projectId}/autoresearch/${pipelineId}/training_runs/${id}/iterations/`
}

/**
 * Record one iteration of an open training run. Idempotent on iteration_number — re-sending the same number updates that iteration. The recipe is validated server-side: model_class must be in the allowlist and feature_sql must be a read-only SELECT keyed on person_id.
 * @summary Record a training iteration
 */
export const autoresearchTrainingRunsIterationsCreate = async (
    projectId: string,
    pipelineId: string,
    id: string,
    recordIterationApi: RecordIterationApi,
    options?: RequestInit
): Promise<AutoresearchIterationApi> => {
    return apiMutator<AutoresearchIterationApi>(
        getAutoresearchTrainingRunsIterationsCreateUrl(projectId, pipelineId, id),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(recordIterationApi),
        }
    )
}

export const getAutoresearchTrainingRunsMaterializeFeaturesCreateUrl = (
    projectId: string,
    pipelineId: string,
    id: string
) => {
    return `/api/projects/${projectId}/autoresearch/${pipelineId}/training_runs/${id}/materialize-features/`
}

/**
 * Run features_sql server-side against the labeled training population and write the resulting train/holdout feature and label parquet files directly into this run's sandbox. Returns the local sandbox paths, row counts, and feature columns. The rows never pass through the agent's context and there is no 500-row cap. Read the returned paths with pd.read_parquet and iterate in Python.
 * @summary Materialize training features to the sandbox
 */
export const autoresearchTrainingRunsMaterializeFeaturesCreate = async (
    projectId: string,
    pipelineId: string,
    id: string,
    materializeFeaturesRequestApi: MaterializeFeaturesRequestApi,
    options?: RequestInit
): Promise<MaterializeFeaturesResponseApi> => {
    return apiMutator<MaterializeFeaturesResponseApi>(
        getAutoresearchTrainingRunsMaterializeFeaturesCreateUrl(projectId, pipelineId, id),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(materializeFeaturesRequestApi),
        }
    )
}

export const getAutoresearchTrainingRunsHistoryRetrieveUrl = (
    projectId: string,
    pipelineId: string,
    params?: AutoresearchTrainingRunsHistoryRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/autoresearch/${pipelineId}/training_runs/history/?${stringifiedParams}`
        : `/api/projects/${projectId}/autoresearch/${pipelineId}/training_runs/history/`
}

/**
 * Return recent completed training runs and their iteration trails so a new run can learn from what was already tried. Scoped to this pipeline first, then same-target sibling pipelines on the team. Read this before iterating to reuse winning features and avoid repeating discarded approaches.
 * @summary Read prior training-run history
 */
export const autoresearchTrainingRunsHistoryRetrieve = async (
    projectId: string,
    pipelineId: string,
    params?: AutoresearchTrainingRunsHistoryRetrieveParams,
    options?: RequestInit
): Promise<TrainingRunHistoryApi> => {
    return apiMutator<TrainingRunHistoryApi>(
        getAutoresearchTrainingRunsHistoryRetrieveUrl(projectId, pipelineId, params),
        {
            ...options,
            method: 'GET',
        }
    )
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

export const getAutoresearchValidateOnlineCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/autoresearch/${id}/validate-online/`
}

/**
 * Validate predictions against realized outcomes for all matured prediction dates. A prediction date is matured when today >= prediction_date + horizon_days. Computes realized AUC, Brier score, calibration error (ECE), and lift@10/20 per model. Updates the model's realized_score, calibration_error, and clears the is_preliminary flag. Already-validated dates are skipped. In production this is triggered by the daily Temporal validation workflow after inference runs.
 * @summary Run online validation
 */
export const autoresearchValidateOnlineCreate = async (
    projectId: string,
    id: string,
    autoresearchPipelineApi: NonReadonly<AutoresearchPipelineApi>,
    options?: RequestInit
): Promise<PaginatedAutoresearchRunListApi> => {
    return apiMutator<PaginatedAutoresearchRunListApi>(getAutoresearchValidateOnlineCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(autoresearchPipelineApi),
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
            normalizedParams.append(key, value === null ? 'null' : value.toString())
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
