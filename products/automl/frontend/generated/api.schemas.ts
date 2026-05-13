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
export type AutoMLPipelineDTOStatusEnumApi =
    (typeof AutoMLPipelineDTOStatusEnumApi)[keyof typeof AutoMLPipelineDTOStatusEnumApi]

export const AutoMLPipelineDTOStatusEnumApi = {
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

/**
 * Output shape of an AutoML pipeline.
 */
export interface AutoMLPipelineDTOApi {
    id: string
    team_id: number
    name: string
    description: string
    task_type: TaskTypeEnumApi
    status: AutoMLPipelineDTOStatusEnumApi
    autonomy: AutonomyEnumApi
    config: AutoMLPipelineDTOApiConfig
    training_population: AutoMLPipelineDTOApiTrainingPopulation
    inference_population: AutoMLPipelineDTOApiInferencePopulation
    inference_cadence: CadenceEnumApi
    retraining_cadence: CadenceEnumApi
    output_property_name: string
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
