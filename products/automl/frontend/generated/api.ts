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
    AutoMLModelVersionDTOApi,
    AutoMLPipelineDTOApi,
    AutomlPipelinesListParams,
    AutomlPipelinesModelVersionsActiveRetrieveParams,
    AutomlPipelinesModelVersionsListParams,
    CreatePipelineInputApi,
    PaginatedAutoMLModelVersionDTOListApi,
    PaginatedAutoMLPipelineDTOListApi,
    PatchedUpdatePipelineInputApi,
    RecordTrainingResultInputApi,
    ValidationReportApi,
} from './api.schemas'

export const getAutomlPipelinesListUrl = (projectId: string, params?: AutomlPipelinesListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/automl_pipelines/?${stringifiedParams}`
        : `/api/projects/${projectId}/automl_pipelines/`
}

/**
 * List non-archived pipelines for the team, newest first.
 */
export const automlPipelinesList = async (
    projectId: string,
    params?: AutomlPipelinesListParams,
    options?: RequestInit
): Promise<PaginatedAutoMLPipelineDTOListApi> => {
    return apiMutator<PaginatedAutoMLPipelineDTOListApi>(getAutomlPipelinesListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getAutomlPipelinesCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/automl_pipelines/`
}

/**
 * Create a new pipeline in draft state.
 */
export const automlPipelinesCreate = async (
    projectId: string,
    createPipelineInputApi: CreatePipelineInputApi,
    options?: RequestInit
): Promise<AutoMLPipelineDTOApi> => {
    return apiMutator<AutoMLPipelineDTOApi>(getAutomlPipelinesCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(createPipelineInputApi),
    })
}

export const getAutomlPipelinesRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/automl_pipelines/${id}/`
}

/**
 * Get one pipeline by ID.
 */
export const automlPipelinesRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<AutoMLPipelineDTOApi> => {
    return apiMutator<AutoMLPipelineDTOApi>(getAutomlPipelinesRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getAutomlPipelinesPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/automl_pipelines/${id}/`
}

/**
 * Apply partial config updates. Use start / pause / resume / archive for status transitions.
 */
export const automlPipelinesPartialUpdate = async (
    projectId: string,
    id: string,
    patchedUpdatePipelineInputApi?: PatchedUpdatePipelineInputApi,
    options?: RequestInit
): Promise<AutoMLPipelineDTOApi> => {
    return apiMutator<AutoMLPipelineDTOApi>(getAutomlPipelinesPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedUpdatePipelineInputApi),
    })
}

export const getAutomlPipelinesArchiveCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/automl_pipelines/${id}/archive/`
}

/**
 * Soft-archive a pipeline. Inference stops; history is preserved.
 */
export const automlPipelinesArchiveCreate = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<AutoMLPipelineDTOApi> => {
    return apiMutator<AutoMLPipelineDTOApi>(getAutomlPipelinesArchiveCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
    })
}

export const getAutomlPipelinesModelVersionsListUrl = (
    projectId: string,
    id: string,
    params?: AutomlPipelinesModelVersionsListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/automl_pipelines/${id}/model_versions/?${stringifiedParams}`
        : `/api/projects/${projectId}/automl_pipelines/${id}/model_versions/`
}

/**
 * List every trained model version on a pipeline, newest first.

Archived versions are included — they're the audit trail and the
``$model_version_id`` on past prediction events still needs to resolve.
 */
export const automlPipelinesModelVersionsList = async (
    projectId: string,
    id: string,
    params?: AutomlPipelinesModelVersionsListParams,
    options?: RequestInit
): Promise<PaginatedAutoMLModelVersionDTOListApi> => {
    return apiMutator<PaginatedAutoMLModelVersionDTOListApi>(
        getAutomlPipelinesModelVersionsListUrl(projectId, id, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getAutomlPipelinesModelVersionsCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/automl_pipelines/${id}/model_versions/`
}

/**
 * Persist a completed training run as a new model version.

Always recorded as ``challenger`` by default — promotion to champion is
the explicit ``promote`` action below. Called by the bootstrap and
retraining agents from inside their sandbox after the trainer returns.
 */
export const automlPipelinesModelVersionsCreate = async (
    projectId: string,
    id: string,
    recordTrainingResultInputApi: RecordTrainingResultInputApi,
    options?: RequestInit
): Promise<AutoMLModelVersionDTOApi> => {
    return apiMutator<AutoMLModelVersionDTOApi>(getAutomlPipelinesModelVersionsCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(recordTrainingResultInputApi),
    })
}

export const getAutomlPipelinesModelVersionsPromoteCreateUrl = (projectId: string, id: string, versionId: string) => {
    return `/api/projects/${projectId}/automl_pipelines/${id}/model_versions/${versionId}/promote/`
}

/**
 * Make ``version_id`` the champion for its pipeline.

Atomic: the prior champion (if any) is archived in the same transaction
the target is set to champion. Idempotent — promoting an existing
champion is a no-op. Returns 404 if the version doesn't belong to the
team or pipeline.
 */
export const automlPipelinesModelVersionsPromoteCreate = async (
    projectId: string,
    id: string,
    versionId: string,
    options?: RequestInit
): Promise<AutoMLModelVersionDTOApi> => {
    return apiMutator<AutoMLModelVersionDTOApi>(
        getAutomlPipelinesModelVersionsPromoteCreateUrl(projectId, id, versionId),
        {
            ...options,
            method: 'POST',
        }
    )
}

export const getAutomlPipelinesModelVersionsActiveRetrieveUrl = (
    projectId: string,
    id: string,
    params?: AutomlPipelinesModelVersionsActiveRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/automl_pipelines/${id}/model_versions/active/?${stringifiedParams}`
        : `/api/projects/${projectId}/automl_pipelines/${id}/model_versions/active/`
}

/**
 * Get the model version currently holding a role on a pipeline.

The partial unique constraint guarantees at most one champion and one
challenger per pipeline. Returns 404 when no version holds the role —
the most common cause is a pipeline that hasn't completed bootstrap yet.
 */
export const automlPipelinesModelVersionsActiveRetrieve = async (
    projectId: string,
    id: string,
    params?: AutomlPipelinesModelVersionsActiveRetrieveParams,
    options?: RequestInit
): Promise<AutoMLModelVersionDTOApi> => {
    return apiMutator<AutoMLModelVersionDTOApi>(
        getAutomlPipelinesModelVersionsActiveRetrieveUrl(projectId, id, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getAutomlPipelinesPauseCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/automl_pipelines/${id}/pause/`
}

/**
 * Pause scheduled inference / training for the pipeline.
 */
export const automlPipelinesPauseCreate = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<AutoMLPipelineDTOApi> => {
    return apiMutator<AutoMLPipelineDTOApi>(getAutomlPipelinesPauseCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
    })
}

export const getAutomlPipelinesResumeCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/automl_pipelines/${id}/resume/`
}

/**
 * Resume a paused pipeline.
 */
export const automlPipelinesResumeCreate = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<AutoMLPipelineDTOApi> => {
    return apiMutator<AutoMLPipelineDTOApi>(getAutomlPipelinesResumeCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
    })
}

export const getAutomlPipelinesStartCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/automl_pipelines/${id}/start/`
}

/**
 * Transition a draft pipeline to bootstrap-pending and enqueue the first training run.

The training itself runs in a sandbox via the ``tasks`` product (one
Task per pipeline bootstrap). The task id lands on the pipeline as
``runtime.bootstrap_task_id`` so the agent's progress is traceable.
 */
export const automlPipelinesStartCreate = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<AutoMLPipelineDTOApi> => {
    return apiMutator<AutoMLPipelineDTOApi>(getAutomlPipelinesStartCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
    })
}

export const getAutomlPipelinesValidateCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/automl_pipelines/validate/`
}

/**
 * Run preflight validation against a proposed pipeline config.

Side-effect-free: nothing is written, no pipeline is created. Same body
shape as the create endpoint; call this first so the user can see the
validation report (volume, base rate, leakage warnings, sample plan)
before committing to a pipeline.
 */
export const automlPipelinesValidateCreate = async (
    projectId: string,
    createPipelineInputApi: CreatePipelineInputApi,
    options?: RequestInit
): Promise<ValidationReportApi> => {
    return apiMutator<ValidationReportApi>(getAutomlPipelinesValidateCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(createPipelineInputApi),
    })
}
