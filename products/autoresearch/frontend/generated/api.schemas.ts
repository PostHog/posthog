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
 * * `draft` - Draft
 * * `bootstrapping` - Bootstrapping
 * * `running` - Running
 * * `converged` - Converged
 * * `paused` - Paused
 * * `archived` - Archived
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
 * * `data` - Data
 * * `product` - Product Management
 * * `founder` - Founder
 * * `leadership` - Leadership
 * * `marketing` - Marketing
 * * `sales` - Sales / Success
 * * `student` - Student
 * * `other` - Other
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
    Student: 'student',
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
 * Resolved target definition: {"type": "event"} or {"type": "action", "action_id": N}.
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
    /** Resolved target definition: {"type": "event"} or {"type": "action", "action_id": N}. */
    target_definition: AutoresearchPipelineApiTargetDefinition
    /**
     * Prediction horizon in days. The model predicts whether the target event occurs within this window.
     * @minimum -2147483648
     * @maximum 2147483647
     */
    horizon_days?: number
    /**
     * How far back to look for training examples. Larger windows give more data but may include stale behavior.
     * @minimum -2147483648
     * @maximum 2147483647
     */
    training_lookback_days?: number
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
     *
     * * `draft` - Draft
     * * `bootstrapping` - Bootstrapping
     * * `running` - Running
     * * `converged` - Converged
     * * `paused` - Paused
     * * `archived` - Archived */
    readonly status: AutoresearchPipelineStatusEnumApi
    readonly created_by: UserBasicApi
    readonly created_at: string
    readonly updated_at: string
    /**
     * Timestamp of the most recent completed inference run.
     * @nullable
     */
    readonly last_scored_at: string | null
    /**
     * Offline holdout AUC of the current champion model (predictive accuracy on held-out training data).
     * @nullable
     */
    readonly champion_holdout_auc: number | null
    /**
     * Realized online AUC of the current champion model, computed from mature predictions against actual outcomes.
     * @nullable
     */
    readonly champion_realized_auc: number | null
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
 * Omit (or pass {"type": "event"}) to predict target_event; pass {"type": "action", "action_id": N} to predict a PostHog action. No other shapes are accepted.
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
     * PostHog event name to predict, e.g. '$pageview' or 'signed_up'. Omit when predicting an action target (pass target_definition instead).
     * @maxLength 255
     */
    target_event?: string
    /** Omit (or pass {"type": "event"}) to predict target_event; pass {"type": "action", "action_id": N} to predict a PostHog action. No other shapes are accepted. */
    target_definition?: AutoresearchPipelineCreateApiTargetDefinition
    /**
     * Prediction horizon in days (1-365). The model predicts whether the target event occurs within this window.
     * @minimum 1
     * @maximum 365
     */
    horizon_days?: number
    /**
     * How far back to look for training examples (7-730 days). Larger windows give more data but may include stale behavior. Default: 180.
     * @minimum 7
     * @maximum 730
     */
    training_lookback_days?: number
    /** Training population filter. Use {} for all identified users. */
    training_population?: AutoresearchPipelineCreateApiTrainingPopulation
    /** Inference population filter. Defaults to training_population if not set. */
    inference_population?: AutoresearchPipelineCreateApiInferencePopulation
    /**
     * Re-score the inference population every N days (1-365). Default: 1.
     * @minimum 1
     * @maximum 365
     */
    cadence_days?: number
    /**
     * Total training iterations allowed for the autoresearch loop (1-500). Default: 50.
     * @minimum 1
     * @maximum 500
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
     * Person property name for the prediction score, e.g. 'predicted_p_pageview'. Auto-derived from target_event if omitted. Letters, digits, and _ $ . - only; must be unique among this project's non-archived pipelines.
     * @maxLength 255
     */
    output_person_property?: string
}

/**
 * Omit (or pass {"type": "event"}) to predict target_event; pass {"type": "action", "action_id": N} to predict a PostHog action. No other shapes are accepted.
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
     * PostHog event name to predict, e.g. '$pageview' or 'signed_up'. Omit when predicting an action target (pass target_definition instead).
     * @maxLength 255
     */
    target_event?: string
    /** Omit (or pass {"type": "event"}) to predict target_event; pass {"type": "action", "action_id": N} to predict a PostHog action. No other shapes are accepted. */
    target_definition?: PatchedAutoresearchPipelineCreateApiTargetDefinition
    /**
     * Prediction horizon in days (1-365). The model predicts whether the target event occurs within this window.
     * @minimum 1
     * @maximum 365
     */
    horizon_days?: number
    /**
     * How far back to look for training examples (7-730 days). Larger windows give more data but may include stale behavior. Default: 180.
     * @minimum 7
     * @maximum 730
     */
    training_lookback_days?: number
    /** Training population filter. Use {} for all identified users. */
    training_population?: PatchedAutoresearchPipelineCreateApiTrainingPopulation
    /** Inference population filter. Defaults to training_population if not set. */
    inference_population?: PatchedAutoresearchPipelineCreateApiInferencePopulation
    /**
     * Re-score the inference population every N days (1-365). Default: 1.
     * @minimum 1
     * @maximum 365
     */
    cadence_days?: number
    /**
     * Total training iterations allowed for the autoresearch loop (1-500). Default: 50.
     * @minimum 1
     * @maximum 500
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
     * Person property name for the prediction score, e.g. 'predicted_p_pageview'. Auto-derived from target_event if omitted. Letters, digits, and _ $ . - only; must be unique among this project's non-archived pipelines.
     * @maxLength 255
     */
    output_person_property?: string
}

/**
 * * `likely_active_soon` - likely_active_soon
 * * `at_risk_of_inactivity` - at_risk_of_inactivity
 * * `return_after_first_use` - return_after_first_use
 * * `feature_adoption` - feature_adoption
 * * `repeat_key_behavior` - repeat_key_behavior
 */
export type TemplateKeyEnumApi = (typeof TemplateKeyEnumApi)[keyof typeof TemplateKeyEnumApi]

export const TemplateKeyEnumApi = {
    LikelyActiveSoon: 'likely_active_soon',
    AtRiskOfInactivity: 'at_risk_of_inactivity',
    ReturnAfterFirstUse: 'return_after_first_use',
    FeatureAdoption: 'feature_adoption',
    RepeatKeyBehavior: 'repeat_key_behavior',
} as const

export interface ResolveTemplateRequestApi {
    /** Template to resolve. Use autoresearch-templates-list to see all available templates with descriptions. Required.
     *
     * * `likely_active_soon` - likely_active_soon
     * * `at_risk_of_inactivity` - at_risk_of_inactivity
     * * `return_after_first_use` - return_after_first_use
     * * `feature_adoption` - feature_adoption
     * * `repeat_key_behavior` - repeat_key_behavior */
    template_key: TemplateKeyEnumApi
    /** Event or action name to use as the prediction target. Required for 'feature_adoption' and 'repeat_key_behavior'. Optional override for activity-based templates ('likely_active_soon', 'at_risk_of_inactivity', 'return_after_first_use') — omit to use the auto-resolved event. */
    target_event?: string
    /**
     * Override the template's default prediction horizon in days.
     * @minimum 1
     * @maximum 365
     */
    horizon_days?: number
}

/**
 * Resolved training population filter. Pass as 'training_population' to autoresearch-create.
 */
export type ResolvedTemplateApiTrainingPopulation = { [key: string]: unknown }

/**
 * Resolved inference (daily scoring) population filter. Pass as 'inference_population' to autoresearch-create.
 */
export type ResolvedTemplateApiInferencePopulation = { [key: string]: unknown }

export interface ResolvedTemplateApi {
    /** The template key that was resolved. */
    template_key: string
    /** Human-readable template name. */
    display_name: string
    /** What this template predicts. */
    description: string
    /** Suggested pipeline name. Pass as 'name' to autoresearch-create. */
    suggested_name: string
    /** Resolved target event. Pass as 'target_event' to autoresearch-create. For activity-based templates this is the auto-resolved activity event (or your override). */
    target_event: string
    /**
     * Activity event found in your event schema, populated only for templates that auto-resolve the target ('likely_active_soon', 'at_risk_of_inactivity', 'return_after_first_use'). Null for templates where you supply target_event directly.
     * @nullable
     */
    resolved_activity_event: string | null
    /** Other viable activity events found in your schema. If the resolved event is not the right signal, re-resolve with one of these as target_event. */
    activity_event_alternatives: string[]
    /** Resolved prediction horizon in days. */
    horizon_days: number
    /** Resolved training population filter. Pass as 'training_population' to autoresearch-create. */
    training_population: ResolvedTemplateApiTrainingPopulation
    /** Resolved inference (daily scoring) population filter. Pass as 'inference_population' to autoresearch-create. */
    inference_population: ResolvedTemplateApiInferencePopulation
    /** Suggested person property name for prediction scores. Pass as 'output_person_property' to autoresearch-create. */
    output_person_property: string
    /** Usage notes and guidance for interpreting this resolved config. */
    notes: string
}

export interface TemplateInfoApi {
    /** Template identifier, e.g. 'likely_active_soon'. Pass to autoresearch-resolve-template-create. */
    key: string
    /** Human-readable template name. */
    display_name: string
    /** What this template predicts and who it is for. */
    description: string
    /** Default prediction horizon in days. Can be overridden when resolving. */
    default_horizon_days: number
    /** If true, you must supply a target_event when resolving — the template does not auto-select one. Required for 'feature_adoption' and 'repeat_key_behavior'. */
    requires_user_event: boolean
    /** If true, the target event is automatically resolved from your event schema ($pageview, $screen, or the highest-volume non-noisy event). You can override the resolved event when resolving the template. */
    requires_activity_resolution: boolean
    /** Usage guidance and implementation notes. */
    notes: string
}

export interface PaginatedTemplateInfoListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: TemplateInfoApi[]
}

/**
 * Population filter for training examples. Use {} for all identified users.
 */
export type ValidatePipelineRequestApiTrainingPopulation = { [key: string]: unknown }

/**
 * Population filter for daily scoring. Defaults to training_population if not provided.
 */
export type ValidatePipelineRequestApiInferencePopulation = { [key: string]: unknown }

export interface ValidatePipelineRequestApi {
    /** Event name to predict, e.g. '$pageview'. Must exist in the team's event schema. Omit when predicting an action target (pass target_definition instead). */
    target_event?: string
    /** Optional target definition. Pass {"type": "action", "action_id": N} to predict a PostHog action (multi-step / property / autocapture matcher) instead of a single event. */
    target_definition?: unknown
    /**
     * Predict whether the target event occurs within this many days.
     * @minimum 1
     * @maximum 365
     */
    horizon_days?: number
    /**
     * How far back to look for training examples. Default: 180.
     * @minimum 7
     * @maximum 730
     */
    training_lookback_days?: number
    /** Population filter for training examples. Use {} for all identified users. */
    training_population?: ValidatePipelineRequestApiTrainingPopulation
    /** Population filter for daily scoring. Defaults to training_population if not provided. */
    inference_population?: ValidatePipelineRequestApiInferencePopulation
}

/**
 * * `info` - info
 * * `warning` - warning
 * * `error` - error
 */
export type IngestionWarningSeverityEnumApi =
    (typeof IngestionWarningSeverityEnumApi)[keyof typeof IngestionWarningSeverityEnumApi]

export const IngestionWarningSeverityEnumApi = {
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
     *
     * * `info` - info
     * * `warning` - warning
     * * `error` - error */
    severity: IngestionWarningSeverityEnumApi
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

export type AutoresearchTemplatesListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}
