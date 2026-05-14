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
    AutoMLPipelineRunDTOApi,
    AutomlPipelinesListParams,
    AutomlPipelinesModelVersionsActiveRetrieveParams,
    AutomlPipelinesModelVersionsListParams,
    AutomlPipelinesRunsListParams,
    CreatePipelineInputApi,
    PaginatedAutoMLModelVersionDTOListApi,
    PaginatedAutoMLPipelineDTOListApi,
    PaginatedAutoMLPipelineRunDTOListApi,
    PatchedUpdatePipelineInputApi,
    RecordBootstrapOutcomeInputApi,
    RecordEdaResultInputApi,
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

When the request body carries a ``run_id``, the matching
``AutoMLPipelineRun`` is updated in the same transaction so the
pipeline-detail timeline links the new version to the run that
produced it. Agents pull ``run_id`` from the bootstrap brief's
Run context block.
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

export const getAutomlPipelinesRetrainCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/automl_pipelines/${id}/retrain/`
}

/**
 * Dispatch a retraining iteration on an active pipeline.

The pipeline must be ``ACTIVE`` and have a winning run to iterate on
(bootstrap must have landed a champion first). Opens a new
``AutoMLPipelineRun(run_kind=RETRAIN)`` chained via ``parent_run_id``
to the previous winning run, then enqueues a Task that runs the
``automl-retrain`` agent skill inside the AutoML sandbox.

Returns the new run DTO. Pipeline status stays ``ACTIVE`` — retraining
failures don't fail the pipeline (the existing champion keeps serving).
 */
export const automlPipelinesRetrainCreate = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<AutoMLPipelineRunDTOApi> => {
    return apiMutator<AutoMLPipelineRunDTOApi>(getAutomlPipelinesRetrainCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
    })
}

export const getAutomlPipelinesRunsListUrl = (
    projectId: string,
    id: string,
    params?: AutomlPipelinesRunsListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/automl_pipelines/${id}/runs/?${stringifiedParams}`
        : `/api/projects/${projectId}/automl_pipelines/${id}/runs/`
}

/**
 * List every run (bootstrap / retrain / inference) for a pipeline, newest first.

Includes terminal runs (succeeded / failed / aborted) — the pipeline-detail
timeline surfaces the full history. Returns 200 with an empty list if the
pipeline has no runs yet (e.g. before ``start`` is called for the first time).
 */
export const automlPipelinesRunsList = async (
    projectId: string,
    id: string,
    params?: AutomlPipelinesRunsListParams,
    options?: RequestInit
): Promise<PaginatedAutoMLPipelineRunDTOListApi> => {
    return apiMutator<PaginatedAutoMLPipelineRunDTOListApi>(getAutomlPipelinesRunsListUrl(projectId, id, params), {
        ...options,
        method: 'GET',
    })
}

export const getAutomlPipelinesRunsRetrieveUrl = (projectId: string, id: string, runId: string) => {
    return `/api/projects/${projectId}/automl_pipelines/${id}/runs/${runId}/`
}

/**
 * Get one pipeline run by id.

Used by the bootstrap agent to look up its own run mid-flight (e.g. to
confirm a previous ``record_eda_result`` write landed before continuing).
 */
export const automlPipelinesRunsRetrieve = async (
    projectId: string,
    id: string,
    runId: string,
    options?: RequestInit
): Promise<AutoMLPipelineRunDTOApi> => {
    return apiMutator<AutoMLPipelineRunDTOApi>(getAutomlPipelinesRunsRetrieveUrl(projectId, id, runId), {
        ...options,
        method: 'GET',
    })
}

export const getAutomlPipelinesRunsRecordBootstrapOutcomeCreateUrl = (projectId: string, id: string, runId: string) => {
    return `/api/projects/${projectId}/automl_pipelines/${id}/runs/${runId}/record_bootstrap_outcome/`
}

/**
 * Flip a run to a terminal state and write the agent's final outcome report.

Single-shot — once a run reaches a terminal state, re-calling this no-ops
(returns the already-terminal DTO). Lets the agent retry the MCP call
after a transient network blip without overwriting the timeline.
Rejects ``status='running'`` with 400 (terminal status required).
 */
export const automlPipelinesRunsRecordBootstrapOutcomeCreate = async (
    projectId: string,
    id: string,
    runId: string,
    recordBootstrapOutcomeInputApi: RecordBootstrapOutcomeInputApi,
    options?: RequestInit
): Promise<AutoMLPipelineRunDTOApi> => {
    return apiMutator<AutoMLPipelineRunDTOApi>(
        getAutomlPipelinesRunsRecordBootstrapOutcomeCreateUrl(projectId, id, runId),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(recordBootstrapOutcomeInputApi),
        }
    )
}

export const getAutomlPipelinesRunsRecordEdaResultCreateUrl = (projectId: string, id: string, runId: string) => {
    return `/api/projects/${projectId}/automl_pipelines/${id}/runs/${runId}/record_eda_result/`
}

/**
 * Stash the agent's EDA output on an in-progress run.

Called by the bootstrap agent between ``automl eda`` and ``automl train``.
Status stays at ``running`` — EDA is a mid-run checkpoint, not terminal.
Idempotent in the sense that a second call overwrites the prior payload
(the CLI's ``eda.yaml`` is regenerated on every re-run).
 */
export const automlPipelinesRunsRecordEdaResultCreate = async (
    projectId: string,
    id: string,
    runId: string,
    recordEdaResultInputApi: RecordEdaResultInputApi,
    options?: RequestInit
): Promise<AutoMLPipelineRunDTOApi> => {
    return apiMutator<AutoMLPipelineRunDTOApi>(getAutomlPipelinesRunsRecordEdaResultCreateUrl(projectId, id, runId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(recordEdaResultInputApi),
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
