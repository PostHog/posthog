/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
/**
 * * `clustering` - CLUSTERING
 * `classification` - CLASSIFICATION
 * `regression` - REGRESSION
 * `forecasting` - FORECASTING
 */
export type TaskTypeEnumApi = (typeof TaskTypeEnumApi)[keyof typeof TaskTypeEnumApi]

export const TaskTypeEnumApi = {
    Clustering: 'clustering',
    Classification: 'classification',
    Regression: 'regression',
    Forecasting: 'forecasting',
} as const

/**
 * * `draft` - DRAFT
 * `bootstrap_pending` - BOOTSTRAP_PENDING
 * `bootstrap_running` - BOOTSTRAP_RUNNING
 * `active` - ACTIVE
 * `paused` - PAUSED
 * `archived` - ARCHIVED
 * `failed` - FAILED
 */
export type PipelineStatusEnumApi = (typeof PipelineStatusEnumApi)[keyof typeof PipelineStatusEnumApi]

export const PipelineStatusEnumApi = {
    Draft: 'draft',
    BootstrapPending: 'bootstrap_pending',
    BootstrapRunning: 'bootstrap_running',
    Active: 'active',
    Paused: 'paused',
    Archived: 'archived',
    Failed: 'failed',
} as const

/**
 * * `shadow_only` - SHADOW_ONLY
 * `champion_only` - CHAMPION_ONLY
 * `promote_eligible` - PROMOTE_ELIGIBLE
 */
export type AutonomyEnumApi = (typeof AutonomyEnumApi)[keyof typeof AutonomyEnumApi]

export const AutonomyEnumApi = {
    ShadowOnly: 'shadow_only',
    ChampionOnly: 'champion_only',
    PromoteEligible: 'promote_eligible',
} as const

/**
 * * `hourly` - HOURLY
 * `daily` - DAILY
 * `weekly` - WEEKLY
 * `monthly` - MONTHLY
 * `never` - NEVER
 */
export type CadenceEnumApi = (typeof CadenceEnumApi)[keyof typeof CadenceEnumApi]

export const CadenceEnumApi = {
    Hourly: 'hourly',
    Daily: 'daily',
    Weekly: 'weekly',
    Monthly: 'monthly',
    Never: 'never',
} as const

export type AutoMLPipelineDTOApiConfig = { [key: string]: unknown }

export type AutoMLPipelineDTOApiTrainingPopulation = { [key: string]: unknown }

export type AutoMLPipelineDTOApiInferencePopulation = { [key: string]: unknown }

export type AutoMLPipelineDTOApiRuntime = { [key: string]: unknown }

/**
 * Output shape of an AutoML pipeline.
 */
export interface AutoMLPipelineDTOApi {
    id: string
    team_id: number
    name: string
    description: string
    task_type: TaskTypeEnumApi
    status: PipelineStatusEnumApi
    autonomy: AutonomyEnumApi
    config: AutoMLPipelineDTOApiConfig
    training_population: AutoMLPipelineDTOApiTrainingPopulation
    inference_population: AutoMLPipelineDTOApiInferencePopulation
    inference_cadence: CadenceEnumApi
    retraining_cadence: CadenceEnumApi
    output_property_name: string
    runtime: AutoMLPipelineDTOApiRuntime
    /** @nullable */
    created_by_id: number | null
    created_at: string
    updated_at: string
}

export interface PaginatedAutoMLPipelineDTOListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: AutoMLPipelineDTOApi[]
}

export type CreatePipelineInputApiConfig = { [key: string]: unknown }

export type CreatePipelineInputApiTrainingPopulation = { [key: string]: unknown }

export type CreatePipelineInputApiInferencePopulation = { [key: string]: unknown }

/**
 * Request body for ``POST /automl_pipelines/``.

``team_id`` and ``created_by_id`` are injected by the view from the
request scope and aren't part of the DTO.
 */
export interface CreatePipelineInputApi {
    name: string
    task_type: TaskTypeEnumApi
    config: CreatePipelineInputApiConfig
    training_population: CreatePipelineInputApiTrainingPopulation
    inference_population: CreatePipelineInputApiInferencePopulation
    description?: string
    autonomy?: AutonomyEnumApi
    inference_cadence?: CadenceEnumApi
    retraining_cadence?: CadenceEnumApi
    output_property_name?: string
}

/**
 * @nullable
 */
export type PatchedUpdatePipelineInputApiConfig = { [key: string]: unknown } | null

/**
 * @nullable
 */
export type PatchedUpdatePipelineInputApiTrainingPopulation = { [key: string]: unknown } | null

/**
 * @nullable
 */
export type PatchedUpdatePipelineInputApiInferencePopulation = { [key: string]: unknown } | null

export type PatchedUpdatePipelineInputApiExtra = { [key: string]: unknown }

/**
 * Request body for ``PATCH /automl_pipelines/{id}/``.

All fields are optional; ``None`` means leave unchanged. Status
transitions go through the dedicated start / pause / resume / archive
actions instead of this endpoint.
 */
export interface PatchedUpdatePipelineInputApi {
    /** @nullable */
    name?: string | null
    /** @nullable */
    description?: string | null
    autonomy?: AutonomyEnumApi | null
    inference_cadence?: CadenceEnumApi | null
    retraining_cadence?: CadenceEnumApi | null
    /** @nullable */
    output_property_name?: string | null
    /** @nullable */
    config?: PatchedUpdatePipelineInputApiConfig
    /** @nullable */
    training_population?: PatchedUpdatePipelineInputApiTrainingPopulation
    /** @nullable */
    inference_population?: PatchedUpdatePipelineInputApiInferencePopulation
    extra?: PatchedUpdatePipelineInputApiExtra
}

export type AutoMLPipelineRunDTOApiEdaResult = { [key: string]: unknown }

export type AutoMLPipelineRunDTOApiTrainingResult = { [key: string]: unknown }

export type AutoMLPipelineRunDTOApiInferenceResult = { [key: string]: unknown }

/**
 * * `bootstrap` - BOOTSTRAP
 * `retrain` - RETRAIN
 * `inference` - INFERENCE
 */
export type AutoMLRunKindEnumApi = (typeof AutoMLRunKindEnumApi)[keyof typeof AutoMLRunKindEnumApi]

export const AutoMLRunKindEnumApi = {
    Bootstrap: 'bootstrap',
    Retrain: 'retrain',
    Inference: 'inference',
} as const

/**
 * * `running` - RUNNING
 * `succeeded` - SUCCEEDED
 * `failed` - FAILED
 * `aborted` - ABORTED
 */
export type AutoMLRunStatusEnumApi = (typeof AutoMLRunStatusEnumApi)[keyof typeof AutoMLRunStatusEnumApi]

export const AutoMLRunStatusEnumApi = {
    Running: 'running',
    Succeeded: 'succeeded',
    Failed: 'failed',
    Aborted: 'aborted',
} as const

/**
 * Output shape of one bootstrap / retrain / inference run on a pipeline.

Durable per-run record — holds the agent's outcome report, EDA summary,
training summary, and failure reason. The pipeline-detail timeline reads
these rows directly; the retraining iteration chain threads them via
``parent_run_id``.
 */
export interface AutoMLPipelineRunDTOApi {
    id: string
    pipeline_id: string
    team_id: number
    run_kind: AutoMLRunKindEnumApi
    status: AutoMLRunStatusEnumApi
    task_slug: string
    task_workspace_root: string
    cli_run_id: string
    agent_session_id: string
    /** @nullable */
    task_id: string | null
    started_at: string
    /** @nullable */
    completed_at: string | null
    outcome_report: string
    eda_result: AutoMLPipelineRunDTOApiEdaResult
    training_result: AutoMLPipelineRunDTOApiTrainingResult
    inference_result: AutoMLPipelineRunDTOApiInferenceResult
    failure_reason: string
    /** @nullable */
    created_model_version_id: string | null
    /** @nullable */
    parent_run_id: string | null
    created_at: string
    updated_at: string
}

/**
 * * `champion` - CHAMPION
 * `challenger` - CHALLENGER
 * `archived` - ARCHIVED
 */
export type RoleEnumApi = (typeof RoleEnumApi)[keyof typeof RoleEnumApi]

export const RoleEnumApi = {
    Champion: 'champion',
    Challenger: 'challenger',
    Archived: 'archived',
} as const

export type AutoMLModelVersionDTOApiMetrics = { [key: string]: unknown }

export type AutoMLModelVersionDTOApiLeaderboardItem = { [key: string]: unknown }

export type AutoMLModelVersionDTOApiTrainingParams = { [key: string]: unknown }

export type AutoMLModelVersionDTOApiTrackingMetadata = { [key: string]: unknown }

/**
 * Output shape of one trained model version on a pipeline.

One row per training run; ``id`` is what propagates onto emitted predictions
as ``$model_version_id``. ``role`` (champion / challenger / archived) drives
whether the version serves traffic.
 */
export interface AutoMLModelVersionDTOApi {
    id: string
    pipeline_id: string
    team_id: number
    role: RoleEnumApi
    metrics: AutoMLModelVersionDTOApiMetrics
    leaderboard: AutoMLModelVersionDTOApiLeaderboardItem[]
    training_params: AutoMLModelVersionDTOApiTrainingParams
    tracking_metadata: AutoMLModelVersionDTOApiTrackingMetadata
    eval_metric: string
    problem_type: string
    artifact_uri: string
    features_hash: string
    /** @nullable */
    rows_train: number | null
    /** @nullable */
    rows_val: number | null
    /** @nullable */
    rows_test: number | null
    /** @nullable */
    training_task_id: string | null
    created_at: string
    updated_at: string
}

export interface PaginatedAutoMLModelVersionDTOListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: AutoMLModelVersionDTOApi[]
}

export type RecordTrainingResultInputApiMetrics = { [key: string]: unknown }

export type RecordTrainingResultInputApiLeaderboardItem = { [key: string]: unknown }

export type RecordTrainingResultInputApiTrainingParams = { [key: string]: unknown }

export type RecordTrainingResultInputApiTrackingMetadata = { [key: string]: unknown }

/**
 * Request body for ``POST /automl_pipelines/{id}/model_versions/``.

Called by the bootstrap / retraining agent when a training run finishes.
``role`` defaults to ``challenger`` so a fresh run never auto-displaces the
existing champion — promotion is a separate explicit step.
 */
export interface RecordTrainingResultInputApi {
    metrics: RecordTrainingResultInputApiMetrics
    leaderboard: RecordTrainingResultInputApiLeaderboardItem[]
    role?: RoleEnumApi
    training_params?: RecordTrainingResultInputApiTrainingParams
    tracking_metadata?: RecordTrainingResultInputApiTrackingMetadata
    eval_metric?: string
    problem_type?: string
    artifact_uri?: string
    features_hash?: string
    /** @nullable */
    rows_train?: number | null
    /** @nullable */
    rows_val?: number | null
    /** @nullable */
    rows_test?: number | null
    /** @nullable */
    training_task_id?: string | null
    /** @nullable */
    run_id?: string | null
}

export interface PaginatedAutoMLPipelineRunDTOListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: AutoMLPipelineRunDTOApi[]
}

/**
 * Request body for ``POST /automl_pipelines/{id}/runs/{run_id}/record_bootstrap_outcome/``.

Called by the bootstrap agent as the final checkpoint of a run. Flips the
run to a terminal status and writes the structured markdown outcome report
surfaced on the pipeline-detail page.
 */
export interface RecordBootstrapOutcomeInputApi {
    status: AutoMLRunStatusEnumApi
    outcome_report: string
    failure_reason?: string
    cli_run_id?: string
    agent_session_id?: string
}

export type RecordEdaResultInputApiEdaResult = { [key: string]: unknown }

/**
 * Request body for ``POST /automl_pipelines/{id}/runs/{run_id}/record_eda_result/``.

Called by the bootstrap agent between ``automl eda`` and ``automl train``.
The ``eda_result`` payload is schemaless on purpose so the CLI's
``eda.yaml`` shape can evolve without forcing a migration.
 */
export interface RecordEdaResultInputApi {
    eda_result: RecordEdaResultInputApiEdaResult
    cli_run_id?: string
}

export type RecordInferenceOutcomeInputApiInferenceResult = { [key: string]: unknown }

/**
 * Request body for ``POST /automl_pipelines/{id}/runs/{run_id}/record_inference_outcome/``.

Called by the inference agent as the single MCP checkpoint at the end of
a scoring iteration. Stamps the full ``automl refresh-task`` stdout
manifest into ``inference_result``; the PostHog-side event-emission step
reads ``predictions_uri`` out of that blob.
 */
export interface RecordInferenceOutcomeInputApi {
    status: AutoMLRunStatusEnumApi
    outcome_report: string
    inference_result?: RecordInferenceOutcomeInputApiInferenceResult
    failure_reason?: string
    agent_session_id?: string
}

/**
 * * `info` - INFO
 * `warn` - WARN
 * `block` - BLOCK
 */
export type ValidationFindingSeverityEnumApi =
    (typeof ValidationFindingSeverityEnumApi)[keyof typeof ValidationFindingSeverityEnumApi]

export const ValidationFindingSeverityEnumApi = {
    Info: 'info',
    Warn: 'warn',
    Block: 'block',
} as const

export type ValidationFindingApiDetails = { [key: string]: unknown }

export interface ValidationFindingApi {
    severity: ValidationFindingSeverityEnumApi
    code: string
    message: string
    details?: ValidationFindingApiDetails
}

export interface ValidationSummaryApi {
    task_type: TaskTypeEnumApi
    training_population_kind: string
    /** @nullable */
    estimated_training_rows?: number | null
    /** @nullable */
    estimated_inference_rows?: number | null
    /** @nullable */
    estimated_inference_events_per_day?: number | null
    /** @nullable */
    estimated_positive_count?: number | null
    /** @nullable */
    estimated_positive_rate?: number | null
    /** @nullable */
    target_event?: string | null
    /** @nullable */
    estimated_series_count?: number | null
    /** @nullable */
    estimated_rows_per_cluster?: number | null
}

/**
 * Response shape for ``POST /automl_pipelines/validate/``.

``ok`` is true iff no findings have ``block`` severity. The same body shape
as the create endpoint goes in; this report comes out without persisting
anything.
 */
export interface ValidationReportApi {
    ok: boolean
    findings: ValidationFindingApi[]
    summary: ValidationSummaryApi
}

export type AutomlPipelinesListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type AutomlPipelinesModelVersionsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type AutomlPipelinesModelVersionsActiveRetrieveParams = {
    /**
     * Role to look up. Defaults to 'champion'. One of: champion, challenger, archived.
     */
    role?: string
}

export type AutomlPipelinesRunsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}
