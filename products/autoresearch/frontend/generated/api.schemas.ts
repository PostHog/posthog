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
 * * `adoption` - Adoption
 * `continuation` - Continuation
 */
export type AutoresearchPredictionModeEnumApi =
    (typeof AutoresearchPredictionModeEnumApi)[keyof typeof AutoresearchPredictionModeEnumApi]

export const AutoresearchPredictionModeEnumApi = {
    Adoption: 'adoption',
    Continuation: 'continuation',
} as const

/**
 * * `draft` - Draft
 * `bootstrapping` - Bootstrapping
 * `running` - Running
 * `converged` - Converged
 * `paused` - Paused
 * `archived` - Archived
 */
export type AutoresearchPipelineStatusEnumApi =
    (typeof AutoresearchPipelineStatusEnumApi)[keyof typeof AutoresearchPipelineStatusEnumApi]

export const AutoresearchPipelineStatusEnumApi = {
    Draft: 'draft',
    Bootstrapping: 'bootstrapping',
    Running: 'running',
    Converged: 'converged',
    Paused: 'paused',
    Archived: 'archived',
} as const

/**
 * * `engineering` - Engineering
 * `data` - Data
 * `product` - Product Management
 * `founder` - Founder
 * `leadership` - Leadership
 * `marketing` - Marketing
 * `sales` - Sales / Success
 * `other` - Other
 */
export type RoleAtOrganizationEnumApi = (typeof RoleAtOrganizationEnumApi)[keyof typeof RoleAtOrganizationEnumApi]

export const RoleAtOrganizationEnumApi = {
    Engineering: 'engineering',
    Data: 'data',
    Product: 'product',
    Founder: 'founder',
    Leadership: 'leadership',
    Marketing: 'marketing',
    Sales: 'sales',
    Other: 'other',
} as const

export type BlankEnumApi = (typeof BlankEnumApi)[keyof typeof BlankEnumApi]

export const BlankEnumApi = {
    '': '',
} as const

/**
 * @nullable
 */
export type UserBasicApiHedgehogConfig = { [key: string]: unknown } | null

export interface UserBasicApi {
    readonly id: number
    readonly uuid: string
    /**
     * @maxLength 200
     * @nullable
     */
    distinct_id?: string | null
    /** @maxLength 150 */
    first_name?: string
    /** @maxLength 150 */
    last_name?: string
    /** @maxLength 254 */
    email: string
    /** @nullable */
    is_email_verified?: boolean | null
    /** @nullable */
    readonly hedgehog_config: UserBasicApiHedgehogConfig
    role_at_organization?: RoleAtOrganizationEnumApi | BlankEnumApi | null
}

/**
 * Full target definition including event filters and positive-label conditions.
 */
export type AutoresearchPipelineApiTargetDefinition = { [key: string]: unknown }

/**
 * Population used for training. Defines which users can appear as training examples.
 */
export type AutoresearchPipelineApiTrainingPopulation = { [key: string]: unknown }

/**
 * Population scored daily. Typically broader than the training population.
 */
export type AutoresearchPipelineApiInferencePopulation = { [key: string]: unknown }

export interface AutoresearchPipelineApi {
    /** Unique UUID of this pipeline. */
    readonly id: string
    /**
     * Display name for the pipeline.
     * @maxLength 255
     */
    name: string
    /** Optional free-text description. */
    description?: string
    /**
     * PostHog event name to predict, e.g. '$pageview' or 'signed_up'.
     * @maxLength 255
     */
    target_event: string
    /** Full target definition including event filters and positive-label conditions. */
    target_definition: AutoresearchPipelineApiTargetDefinition
    /**
     * Prediction horizon in days. The model predicts whether the target event occurs within this window.
     * @minimum -2147483648
     * @maximum 2147483647
     */
    horizon_days?: number
    /** 'adoption': predict first-time occurrence (users who haven't done it yet). 'continuation': predict repeat occurrence.

  * `adoption` - Adoption
  * `continuation` - Continuation */
    prediction_mode?: AutoresearchPredictionModeEnumApi
    /** Population used for training. Defines which users can appear as training examples. */
    training_population: AutoresearchPipelineApiTrainingPopulation
    /** Population scored daily. Typically broader than the training population. */
    inference_population: AutoresearchPipelineApiInferencePopulation
    /**
     * Re-score the inference population every N days.
     * @minimum -2147483648
     * @maximum 2147483647
     */
    cadence_days?: number
    /**
     * Total training iterations allowed for the autoresearch loop.
     * @minimum -2147483648
     * @maximum 2147483647
     */
    iteration_budget?: number
    /** Iterations remaining in the current budget. */
    readonly iteration_budget_remaining: number
    /**
     * Target AUC threshold. Training stops early if this score is reached.
     * @nullable
     */
    success_auc?: number | null
    /**
     * Stop training if no AUC improvement is seen in this many consecutive iterations.
     * @minimum -2147483648
     * @maximum 2147483647
     */
    plateau_iterations?: number
    /**
     * Person property name that stores the daily prediction score, e.g. 'predicted_p_pageview'.
     * @maxLength 255
     */
    output_person_property?: string
    /** Pipeline lifecycle status: draft, bootstrapping, running, converged, paused, or archived.

  * `draft` - Draft
  * `bootstrapping` - Bootstrapping
  * `running` - Running
  * `converged` - Converged
  * `paused` - Paused
  * `archived` - Archived */
    readonly status: AutoresearchPipelineStatusEnumApi
    readonly created_by: UserBasicApi
    readonly created_at: string
    readonly updated_at: string
    /**
     * Timestamp of the most recent completed inference run.
     * @nullable
     */
    readonly last_scored_at: string | null
}

export interface PaginatedAutoresearchPipelineListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: AutoresearchPipelineApi[]
}

/**
 * Full target definition. Can be left empty to use target_event alone.
 */
export type AutoresearchPipelineCreateApiTargetDefinition = { [key: string]: unknown }

/**
 * Training population filter. Use {} for all identified users.
 */
export type AutoresearchPipelineCreateApiTrainingPopulation = { [key: string]: unknown }

/**
 * Inference population filter. Defaults to training_population if not set.
 */
export type AutoresearchPipelineCreateApiInferencePopulation = { [key: string]: unknown }

export interface AutoresearchPipelineCreateApi {
    /**
     * Display name for the pipeline.
     * @maxLength 255
     */
    name: string
    /** Optional free-text description. */
    description?: string
    /**
     * PostHog event name to predict, e.g. '$pageview' or 'signed_up'.
     * @maxLength 255
     */
    target_event: string
    /** Full target definition. Can be left empty to use target_event alone. */
    target_definition?: AutoresearchPipelineCreateApiTargetDefinition
    /**
     * Prediction horizon in days. The model predicts whether the target event occurs within this window.
     * @minimum -2147483648
     * @maximum 2147483647
     */
    horizon_days?: number
    /** 'adoption': predict first-time occurrence (users who haven't done it yet). 'continuation': predict repeat occurrence.

  * `adoption` - Adoption
  * `continuation` - Continuation */
    prediction_mode?: AutoresearchPredictionModeEnumApi
    /** Training population filter. Use {} for all identified users. */
    training_population?: AutoresearchPipelineCreateApiTrainingPopulation
    /** Inference population filter. Defaults to training_population if not set. */
    inference_population?: AutoresearchPipelineCreateApiInferencePopulation
    /**
     * Re-score the inference population every N days. Default: 1.
     * @minimum -2147483648
     * @maximum 2147483647
     */
    cadence_days?: number
    /**
     * Total training iterations allowed for the autoresearch loop. Default: 50.
     * @minimum -2147483648
     * @maximum 2147483647
     */
    iteration_budget?: number
    /**
     * Target AUC threshold. Training stops early if reached. Default: 0.75.
     * @nullable
     */
    success_auc?: number | null
    /**
     * Stop training if no improvement in this many consecutive iterations. Default: 10.
     * @minimum -2147483648
     * @maximum 2147483647
     */
    plateau_iterations?: number
    /**
     * Person property name for the prediction score. Auto-derived from target_event if omitted, e.g. 'predicted_p_pageview'.
     * @maxLength 255
     */
    output_person_property?: string
}

/**
 * * `champion` - Champion
 * `challenger` - Challenger
 * `archived` - Archived
 */
export type RoleEnumApi = (typeof RoleEnumApi)[keyof typeof RoleEnumApi]

export const RoleEnumApi = {
    Champion: 'champion',
    Challenger: 'challenger',
    Archived: 'archived',
} as const

/**
 * Portable recipe artifact. Feature SQL, transforms, model class, params, and metadata.
 */
export type AutoresearchModelApiModelRecipe = { [key: string]: unknown }

/**
 * Global feature importance and directionality. Used to explain top drivers on the model card.
 */
export type AutoresearchModelApiModelExplanation = { [key: string]: unknown }

export interface AutoresearchModelApi {
    /** Unique UUID of this model version. */
    readonly id: string
    /** Pipeline this model belongs to. */
    pipeline: string
    /** Model role: 'champion' (active scoring model), 'challenger' (shadow model), or 'archived'.

  * `champion` - Champion
  * `challenger` - Challenger
  * `archived` - Archived */
    role?: RoleEnumApi
    /** SHA-256 of the serialized recipe. Used to deduplicate identical recipes across runs. */
    readonly recipe_hash: string
    /** Portable recipe artifact. Feature SQL, transforms, model class, params, and metadata. */
    model_recipe: AutoresearchModelApiModelRecipe
    /** Global feature importance and directionality. Used to explain top drivers on the model card. */
    model_explanation: AutoresearchModelApiModelExplanation
    /**
     * AUC on the held-out test split at training time. Preliminary signal before online labels mature.
     * @nullable
     */
    holdout_score?: number | null
    /**
     * Online AUC computed from actual realized outcomes. Authoritative once enough labels have matured.
     * @nullable
     */
    realized_score?: number | null
    /**
     * Expected calibration error (ECE). Lower is better; well-calibrated models have ECE < 0.05.
     * @nullable
     */
    calibration_error?: number | null
    /** Extended metrics bundle: Brier score, precision/recall at thresholds, lift@k, base rate, row counts. */
    metrics?: unknown
    /** The agent's own plain-English description of what this recipe does and why it was chosen. */
    agent_description?: string
    /**
     * Start of the training data window (inclusive).
     * @nullable
     */
    trained_on_start?: string | null
    /**
     * End of the training data window (exclusive).
     * @nullable
     */
    trained_on_end?: string | null
    /** True if this model has not yet been validated against realized online outcomes. */
    is_preliminary?: boolean
    /**
     * Timestamp when this model was promoted to champion.
     * @nullable
     */
    promoted_at?: string | null
    /**
     * Timestamp when this model was archived (superseded or retired).
     * @nullable
     */
    archived_at?: string | null
    readonly created_at: string
    readonly updated_at: string
}

export interface PaginatedAutoresearchModelListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: AutoresearchModelApi[]
}

/**
 * * `inference` - Inference
 * `validation` - Validation
 * `notebook` - Notebook
 */
export type RunTypeEnumApi = (typeof RunTypeEnumApi)[keyof typeof RunTypeEnumApi]

export const RunTypeEnumApi = {
    Inference: 'inference',
    Validation: 'validation',
    Notebook: 'notebook',
} as const

/**
 * * `pending` - Pending
 * `running` - Running
 * `completed` - Completed
 * `failed` - Failed
 */
export type AutoresearchRunStatusEnumApi =
    (typeof AutoresearchRunStatusEnumApi)[keyof typeof AutoresearchRunStatusEnumApi]

export const AutoresearchRunStatusEnumApi = {
    Pending: 'pending',
    Running: 'running',
    Completed: 'completed',
    Failed: 'failed',
} as const

export interface AutoresearchRunApi {
    /** Unique UUID of this run. */
    readonly id: string
    /** Pipeline this run belongs to. */
    pipeline: string
    /**
     * Model used for scoring. Null for validation or notebook runs.
     * @nullable
     */
    model?: string | null
    /** Type of run: 'inference' (daily scoring), 'validation' (outcome evaluation), or 'notebook' (report generation).

  * `inference` - Inference
  * `validation` - Validation
  * `notebook` - Notebook */
    run_type: RunTypeEnumApi
    /** Run status: pending, running, completed, or failed.

  * `pending` - Pending
  * `running` - Running
  * `completed` - Completed
  * `failed` - Failed */
    status?: AutoresearchRunStatusEnumApi
    /**
     * Number of users scored in this inference run.
     * @minimum -2147483648
     * @maximum 2147483647
     * @nullable
     */
    rows_scored?: number | null
    /** Run metrics: rows scored, score distribution summary, validation AUC, etc. */
    metrics: unknown
    /** Error message if the run failed. */
    error?: string
    /**
     * Timestamp when the run started.
     * @nullable
     */
    started_at?: string | null
    /**
     * Timestamp when the run completed or failed.
     * @nullable
     */
    completed_at?: string | null
    readonly created_at: string
}

export interface PaginatedAutoresearchRunListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: AutoresearchRunApi[]
}

/**
 * * `try_next` - Try next
 * `consider` - Consider
 */
export type AutoresearchSuggestionPriorityEnumApi =
    (typeof AutoresearchSuggestionPriorityEnumApi)[keyof typeof AutoresearchSuggestionPriorityEnumApi]

export const AutoresearchSuggestionPriorityEnumApi = {
    TryNext: 'try_next',
    Consider: 'consider',
} as const

/**
 * * `queued` - Queued
 * `picked_up` - Picked up
 * `acted_on` - Acted on
 * `dismissed` - Dismissed
 */
export type AutoresearchSuggestionStatusEnumApi =
    (typeof AutoresearchSuggestionStatusEnumApi)[keyof typeof AutoresearchSuggestionStatusEnumApi]

export const AutoresearchSuggestionStatusEnumApi = {
    Queued: 'queued',
    PickedUp: 'picked_up',
    ActedOn: 'acted_on',
    Dismissed: 'dismissed',
} as const

/**
 * * `user` - User
 * `agent` - Agent
 */
export type AutoresearchSuggestionSourceEnumApi =
    (typeof AutoresearchSuggestionSourceEnumApi)[keyof typeof AutoresearchSuggestionSourceEnumApi]

export const AutoresearchSuggestionSourceEnumApi = {
    User: 'user',
    Agent: 'agent',
} as const

export interface AutoresearchSuggestionApi {
    /** Unique UUID of this suggestion. */
    readonly id: string
    /** Pipeline this suggestion targets. */
    pipeline: string
    /** Free-text hypothesis or direction for the agent to explore. */
    prompt: string
    /** 'try_next' instructs the agent to act on this before other iterations; 'consider' is advisory.

  * `try_next` - Try next
  * `consider` - Consider */
    priority?: AutoresearchSuggestionPriorityEnumApi
    /** Lifecycle status: 'queued' (awaiting pickup), 'picked_up' (agent is applying as a constraint), 'acted_on' (agent spawned iterations), 'dismissed' (agent rejected with rationale).

  * `queued` - Queued
  * `picked_up` - Picked up
  * `acted_on` - Acted on
  * `dismissed` - Dismissed */
    readonly status: AutoresearchSuggestionStatusEnumApi
    /** 'user' for human-submitted suggestions; 'agent' for agent-generated hypotheses.

  * `user` - User
  * `agent` - Agent */
    readonly source: AutoresearchSuggestionSourceEnumApi
    /** Agent's note on how the suggestion was interpreted and acted upon. Populated after pickup. */
    readonly agent_response: string
    readonly created_by: UserBasicApi
    /** UUIDs of iterations spawned from this suggestion. */
    readonly linked_iteration_ids: readonly string[]
    readonly created_at: string
    readonly updated_at: string
}

export interface PaginatedAutoresearchSuggestionListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: AutoresearchSuggestionApi[]
}

/**
 * * `try_next` - try_next
 * `consider` - consider
 */
export type CreateSuggestionPriorityEnumApi =
    (typeof CreateSuggestionPriorityEnumApi)[keyof typeof CreateSuggestionPriorityEnumApi]

export const CreateSuggestionPriorityEnumApi = {
    TryNext: 'try_next',
    Consider: 'consider',
} as const

export interface CreateSuggestionApi {
    /**
     * Free-text hypothesis or direction for the agent to explore, e.g. 'try a tree-based model' or 'remove recency features, I suspect leakage'.
     * @maxLength 2000
     */
    prompt: string
    /** 'try_next' asks the agent to act on this before other autonomous iterations; 'consider' is advisory context.

  * `try_next` - try_next
  * `consider` - consider */
    priority?: CreateSuggestionPriorityEnumApi
}

export interface AutoresearchTrainingRunApi {
    /** Unique UUID of this training run. */
    readonly id: string
    /** Pipeline this training run belongs to. */
    pipeline: string
    /**
     * Task sandbox run ID. Null for stub/synchronous training runs.
     * @nullable
     */
    task_run_id?: string | null
    /** Run status: pending, running, completed, or failed.

  * `pending` - Pending
  * `running` - Running
  * `completed` - Completed
  * `failed` - Failed */
    readonly status: AutoresearchRunStatusEnumApi
    /**
     * Maximum iterations allowed for this run.
     * @minimum -2147483648
     * @maximum 2147483647
     */
    iteration_budget?: number
    /** Number of iterations completed. */
    readonly iteration_count: number
    /**
     * Best holdout AUC achieved across all iterations in this run.
     * @nullable
     */
    readonly best_holdout_score: number | null
    /** Error message if the run failed. */
    readonly error: string
    /**
     * Timestamp when the training run started.
     * @nullable
     */
    readonly started_at: string | null
    /**
     * Timestamp when the training run completed or failed.
     * @nullable
     */
    readonly completed_at: string | null
    readonly created_at: string
}

export interface PaginatedAutoresearchTrainingRunListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: AutoresearchTrainingRunApi[]
}

/**
 * Full target definition. Can be left empty to use target_event alone.
 */
export type PatchedAutoresearchPipelineCreateApiTargetDefinition = { [key: string]: unknown }

/**
 * Training population filter. Use {} for all identified users.
 */
export type PatchedAutoresearchPipelineCreateApiTrainingPopulation = { [key: string]: unknown }

/**
 * Inference population filter. Defaults to training_population if not set.
 */
export type PatchedAutoresearchPipelineCreateApiInferencePopulation = { [key: string]: unknown }

export interface PatchedAutoresearchPipelineCreateApi {
    /**
     * Display name for the pipeline.
     * @maxLength 255
     */
    name?: string
    /** Optional free-text description. */
    description?: string
    /**
     * PostHog event name to predict, e.g. '$pageview' or 'signed_up'.
     * @maxLength 255
     */
    target_event?: string
    /** Full target definition. Can be left empty to use target_event alone. */
    target_definition?: PatchedAutoresearchPipelineCreateApiTargetDefinition
    /**
     * Prediction horizon in days. The model predicts whether the target event occurs within this window.
     * @minimum -2147483648
     * @maximum 2147483647
     */
    horizon_days?: number
    /** 'adoption': predict first-time occurrence (users who haven't done it yet). 'continuation': predict repeat occurrence.

  * `adoption` - Adoption
  * `continuation` - Continuation */
    prediction_mode?: AutoresearchPredictionModeEnumApi
    /** Training population filter. Use {} for all identified users. */
    training_population?: PatchedAutoresearchPipelineCreateApiTrainingPopulation
    /** Inference population filter. Defaults to training_population if not set. */
    inference_population?: PatchedAutoresearchPipelineCreateApiInferencePopulation
    /**
     * Re-score the inference population every N days. Default: 1.
     * @minimum -2147483648
     * @maximum 2147483647
     */
    cadence_days?: number
    /**
     * Total training iterations allowed for the autoresearch loop. Default: 50.
     * @minimum -2147483648
     * @maximum 2147483647
     */
    iteration_budget?: number
    /**
     * Target AUC threshold. Training stops early if reached. Default: 0.75.
     * @nullable
     */
    success_auc?: number | null
    /**
     * Stop training if no improvement in this many consecutive iterations. Default: 10.
     * @minimum -2147483648
     * @maximum 2147483647
     */
    plateau_iterations?: number
    /**
     * Person property name for the prediction score. Auto-derived from target_event if omitted, e.g. 'predicted_p_pageview'.
     * @maxLength 255
     */
    output_person_property?: string
}

export interface StartTrainingRequestApi {
    /**
     * Override the pipeline iteration budget for this training run.
     * @minimum 1
     * @maximum 500
     */
    iteration_budget?: number
}

/**
 * * `adoption` - adoption
 * `continuation` - continuation
 */
export type ValidatePipelineRequestPredictionModeEnumApi =
    (typeof ValidatePipelineRequestPredictionModeEnumApi)[keyof typeof ValidatePipelineRequestPredictionModeEnumApi]

export const ValidatePipelineRequestPredictionModeEnumApi = {
    Adoption: 'adoption',
    Continuation: 'continuation',
} as const

export interface ValidatePipelineRequestApi {
    /** Event name to predict, e.g. '$pageview'. Must exist in the team's event schema. */
    target_event: string
    /**
     * Predict whether the target event occurs within this many days.
     * @minimum 1
     * @maximum 365
     */
    horizon_days?: number
    /** 'adoption': predict first-time occurrence for users who haven't done it yet. 'continuation': predict repeat occurrence for users who have already done it.

  * `adoption` - adoption
  * `continuation` - continuation */
    prediction_mode?: ValidatePipelineRequestPredictionModeEnumApi
    /** Population filter for training examples. Use {} for all identified users. */
    training_population?: unknown
    /** Population filter for daily scoring. Defaults to training_population if not provided. */
    inference_population?: unknown
}

/**
 * * `info` - info
 * `warning` - warning
 * `error` - error
 */
export type ValidationWarningSeverityEnumApi =
    (typeof ValidationWarningSeverityEnumApi)[keyof typeof ValidationWarningSeverityEnumApi]

export const ValidationWarningSeverityEnumApi = {
    Info: 'info',
    Warning: 'warning',
    Error: 'error',
} as const

export interface ValidationWarningApi {
    /** Machine-readable warning code, e.g. 'low_volume' or 'extreme_imbalance'. */
    code: string
    /** Human-readable warning description. */
    message: string
    /** Severity level. 'error' blocks creation; 'warning' requires acknowledgement.

  * `info` - info
  * `warning` - warning
  * `error` - error */
    severity: ValidationWarningSeverityEnumApi
}

export interface ValidatePipelineResponseApi {
    /** True if the pipeline definition is valid and training can start. */
    can_proceed: boolean
    /** True if there are non-blocking warnings the user should acknowledge before proceeding. */
    requires_acknowledgement: boolean
    /**
     * Estimated number of user-level training rows based on the population and lookback window.
     * @nullable
     */
    estimated_training_rows: number | null
    /**
     * Estimated number of positive examples (users who performed the target event).
     * @nullable
     */
    positive_count: number | null
    /**
     * Estimated number of negative examples.
     * @nullable
     */
    negative_count: number | null
    /**
     * Fraction of the training population that performed the target event.
     * @nullable
     */
    base_rate: number | null
    /**
     * Estimated number of users in the inference (daily scoring) population.
     * @nullable
     */
    inference_population_size: number | null
    /** List of validation warnings. Check 'severity' — 'error' blocks creation. */
    warnings: ValidationWarningApi[]
    /**
     * Internal error message if validation itself failed to run.
     * @nullable
     */
    error: string | null
}

export type AutoresearchListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type AutoresearchModelsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type AutoresearchRunsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type AutoresearchSuggestionsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type AutoresearchTrainingRunsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}
