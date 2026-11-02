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
 * * `7` - 7
 * * `14` - 14
 * * `30` - 30
 * * `60` - 60
 * * `90` - 90
 */
export type ResearchIntervalDaysEnumApi = (typeof ResearchIntervalDaysEnumApi)[keyof typeof ResearchIntervalDaysEnumApi]

export const ResearchIntervalDaysEnumApi = {
    Number7: 7,
    Number14: 14,
    Number30: 30,
    Number60: 60,
    Number90: 90,
} as const

/**
 * * `explore` - Explore
 * * `maintain` - Maintain
 */
export type TrainingPhaseEnumApi = (typeof TrainingPhaseEnumApi)[keyof typeof TrainingPhaseEnumApi]

export const TrainingPhaseEnumApi = {
    Explore: 'explore',
    Maintain: 'maintain',
} as const

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

export interface AutoresearchRealizedAucPointApi {
    /** Validated prediction date. */
    readonly prediction_date: string
    /** Realized AUC on that date. */
    readonly realized_auc: number
}

export interface AutoresearchTrainingTrendPointApi {
    /** Iteration number inside the training run. */
    readonly iteration_number: number
    /** Best holdout AUC of the run up to and including this iteration. */
    readonly best_holdout_score: number
}

export interface AutoresearchPredictionCoverageApi {
    /** People in the inference population at the run's cutoff. */
    readonly population: number
    /** People with a champion score inside the lookback window before the cutoff. Shadow scores do not count. */
    readonly with_score: number
    /** People with no champion score inside the lookback window. A rolling run scores these people first. */
    readonly never_scored: number
    /**
     * Mean age in days of the newest score per person. Null when nobody has a score.
     * @nullable
     */
    readonly age_days_avg: number | null
    /**
     * Median age in days of the newest score per person. Null when nobody has a score.
     * @nullable
     */
    readonly age_days_p50: number | null
    /**
     * 90th percentile age in days of the newest score per person. Null when nobody has a score.
     * @nullable
     */
    readonly age_days_p90: number | null
    /**
     * Oldest score age in days. Null when nobody has a score.
     * @nullable
     */
    readonly age_days_max: number | null
    /** How many days before the cutoff the measure reads scores. Older scores count as never scored. */
    readonly lookback_days: number
}

export interface AutoresearchLiveTrainingRunApi {
    /** Unique UUID of the live training run. */
    readonly id: string
    /** Maximum experiments allowed for this run. */
    readonly iteration_budget: number
    /** Experiments the agent has recorded so far in this run. */
    readonly experiment_count: number
    /**
     * Best holdout AUC so far in this run. Null before any is recorded.
     * @nullable
     */
    readonly best_holdout_score: number | null
    /** The agent's rationale for its newest experiment. */
    readonly latest_agent_description: string
    /**
     * Plain-language sentence on the newest experiment, for people. Null if the agent wrote none.
     * @nullable
     */
    readonly latest_summary: string | null
    /** Best-so-far holdout AUC per experiment of this run, oldest first. Experiments before the first holdout score are left out. */
    readonly trend: readonly AutoresearchTrainingTrendPointApi[]
}

/**
 * Resolved target definition: {"type": "event"} or {"type": "action", "action_id": N}.
 */
export type AutoresearchPipelineApiTargetDefinition =
    | {
          type: 'event'
      }
    | {
          type: 'action'
          /**
           * ID of the action to predict.
           * @minimum 1
           */
          action_id: number
      }

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
     * Deprecated: scheduled training no longer reads it. Use iterations_per_run.
     * @minimum -2147483648
     * @maximum 2147483647
     */
    iteration_budget?: number
    /** Deprecated: scheduled training no longer reads or spends it. */
    readonly iteration_budget_remaining: number
    /** Experiments the agent may try in each training run (1-50). Each experiment costs agent time and queries, so a higher value costs more per run. Scheduled runs and Train now use it. */
    readonly iterations_per_run: number
    /** Days between scheduled research runs once the first burst of daily runs ends: 7, 14, 30, 60 or 90. Null means only when asked: no scheduled research, so the only training cost comes from runs you start and from rescue runs for a model that cannot score. A shorter interval costs more.
     *
     * * `7` - 7
     * * `14` - 14
     * * `30` - 30
     * * `60` - 60
     * * `90` - 90 */
    readonly research_interval_days: ResearchIntervalDaysEnumApi | null
    /**
     * Model the training agent runs on, as set on this pipeline. Null uses the autoresearch default.
     * @nullable
     */
    readonly agent_model: string | null
    /**
     * Reasoning effort for the training agent, as set on this pipeline. Null uses the autoresearch default.
     * @nullable
     */
    readonly agent_reasoning_effort: string | null
    /** Model the next training run uses: agent_model, or the autoresearch default when that is null. */
    readonly effective_agent_model: string
    /**
     * Reasoning effort the next training run uses: agent_reasoning_effort, or the autoresearch default when that is null. Null when the model has no effort setting.
     * @nullable
     */
    readonly effective_agent_reasoning_effort: string | null
    /** explore: a research run on each scoring day until a run does not promote a better model, or until 5 research runs have run. maintain: one research run every research_interval_days.
     *
     * * `explore` - Explore
     * * `maintain` - Maintain */
    readonly training_phase: TrainingPhaseEnumApi
    /**
     * Start of the UTC day from which the daily sweep can start the next scheduled research run. Null when research_interval_days is null.
     * @nullable
     */
    readonly next_research_at: string | null
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
    /** Whether live scoring writes the champion's score to output_person_property on each scored person. Feature flags, cohorts, workflows and insights that target people by score need it on. */
    readonly write_person_property: boolean
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
    /**
     * Lift in the top 10% of scores for the current champion model, from its latest validated prediction date. 2.0 means the top 10% converts at twice the average rate.
     * @nullable
     */
    readonly champion_lift_at_10: number | null
    /**
     * True while the current champion model has no realized AUC yet. Null when the pipeline has no champion.
     * @nullable
     */
    readonly champion_is_preliminary: boolean | null
    /** Realized AUC of the current champion on its newest 14 validated prediction dates, oldest first. */
    readonly champion_realized_auc_trend: readonly AutoresearchRealizedAucPointApi[]
    /** Best-so-far holdout AUC per iteration of the training run that produced the current champion, oldest first. Iterations before the first holdout score are left out. Empty when the pipeline has no champion. */
    readonly champion_training_trend: readonly AutoresearchTrainingTrendPointApi[]
    /**
     * People scored by the most recent completed inference run. Null before the first scoring run.
     * @nullable
     */
    readonly people_scored: number | null
    /**
     * People the newest completed live run of the current champion scored at or above likely_threshold. Null before such a run, and for runs that did not record it.
     * @nullable
     */
    readonly likely_count: number | null
    /**
     * The Likely cut point that likely_count used, as it was when that run scored. It is the fixed cut point until enough predictions are checked. Null when likely_count is null.
     * @nullable
     */
    readonly likely_threshold: number | null
    /**
     * When online validation can first check the current champion against real outcomes: its earliest prediction date plus the horizon plus the ingestion grace. Null before the champion's first scoring run, and once a validation has checked it.
     * @nullable
     */
    readonly first_check_expected_at: string | null
    /** Score coverage and score age from the newest live champion run that measured them. Null before the first such run. */
    readonly coverage: AutoresearchPredictionCoverageApi | null
    /** Training runs started for this pipeline. */
    readonly training_run_count: number
    /** Experiments (iterations) recorded across every training run. */
    readonly experiment_count: number
    /** Progress of the pending or running training run. Null when no run is live. */
    readonly live_training_run: AutoresearchLiveTrainingRunApi | null
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
export type AutoresearchPipelineCreateApiTargetDefinition =
    | {
          type: 'event'
      }
    | {
          type: 'action'
          /**
           * ID of the action to predict.
           * @minimum 1
           */
          action_id: number
      }

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
     * Deprecated: scheduled training no longer reads it. Use iterations_per_run.
     * @minimum 1
     * @maximum 500
     */
    iteration_budget?: number
    /**
     * Experiments the agent may try in each training run (1-50). Each experiment costs agent time and queries, so a higher value costs more per run. Scheduled runs and Train now use it. Default: 5.
     * @minimum 1
     * @maximum 50
     */
    iterations_per_run?: number
    /** Days between scheduled research runs once the first burst of daily runs ends: 7, 14, 30, 60 or 90. Null means only when asked: no scheduled research, so the only training cost comes from runs you start and from rescue runs for a model that cannot score. A shorter interval costs more. Default: 7.
     *
     * * `7` - 7
     * * `14` - 14
     * * `30` - 30
     * * `60` - 60
     * * `90` - 90 */
    research_interval_days?: ResearchIntervalDaysEnumApi | null
    /**
     * Model the training agent runs on, a model id from the PostHog Tasks catalogue such as 'claude-opus-5-5', 'claude-sonnet-5-5' or 'gpt-6.1-sol'. Null or omitted uses the autoresearch default, Claude Opus 5.5. A larger model costs more per training run. Scheduled runs and Train now use it.
     * @maxLength 100
     * @nullable
     */
    agent_model?: string | null
    /**
     * Reasoning effort for the training agent, such as 'low', 'medium' or 'high'. It must be one the model supports, and without agent_model it is checked against the default model. Null or omitted uses the autoresearch default, medium. Higher effort costs more per training run.
     * @maxLength 20
     * @nullable
     */
    agent_reasoning_effort?: string | null
    /**
     * Target AUC threshold (0-1). Training stops early if reached. Default: 0.75.
     * @minimum 0
     * @maximum 1
     * @nullable
     */
    success_auc?: number | null
    /**
     * Stop training if no improvement in this many consecutive iterations (at least 1). Default: 10.
     * @minimum 1
     * @maximum 2147483647
     */
    plateau_iterations?: number
    /**
     * Person property name for the prediction score, e.g. 'predicted_p_pageview'. Auto-derived from target_event if omitted. Letters, digits, and _ $ . - only, and it cannot start with $ (reserved for PostHog's own properties); must be unique among this project's non-archived pipelines.
     * @maxLength 255
     */
    output_person_property?: string
    /** Write the champion's score to output_person_property on each scored person at every live scoring run. Default: false. Needed to target people by score in feature flags, cohorts, workflows and insights. Prediction events, validation and segments work without it. Turning it off, or archiving or deleting the pipeline while it is on, removes the property from the people it scored. */
    write_person_property?: boolean
}

/**
 * * `champion` - Champion
 * * `challenger` - Challenger
 * * `archived` - Archived
 */
export type AutoresearchModelRoleEnumApi =
    (typeof AutoresearchModelRoleEnumApi)[keyof typeof AutoresearchModelRoleEnumApi]

export const AutoresearchModelRoleEnumApi = {
    Champion: 'champion',
    Challenger: 'challenger',
    Archived: 'archived',
} as const

/**
 * * `positive` - Positive
 * * `negative` - Negative
 */
export type FeatureDirectionEnumApi = (typeof FeatureDirectionEnumApi)[keyof typeof FeatureDirectionEnumApi]

export const FeatureDirectionEnumApi = {
    Positive: 'positive',
    Negative: 'negative',
} as const

export interface FeatureImportanceApi {
    /**
     * Feature column name, as returned by the feature SQL.
     * @maxLength 200
     */
    name: string
    /**
     * Non-negative importance, for example the mean holdout AUC drop when the feature is shuffled.
     * @minimum 0
     */
    importance: number
    /** 'positive' if a higher value raises the predicted probability, 'negative' if it lowers it.
     *
     * * `positive` - Positive
     * * `negative` - Negative */
    direction: FeatureDirectionEnumApi
}

/**
 * Global feature importances for the model card.
 */
export interface ModelExplanationFieldApi {
    /**
     * At most 30 features, strongest first.
     * @maxItems 30
     */
    top_features?: FeatureImportanceApi[]
    /**
     * Short description of how the importances were computed, e.g. 'permutation importance on holdout'.
     * @maxLength 500
     */
    method?: string
    /**
     * Optional caveat shown under the chart.
     * @maxLength 500
     */
    note?: string
}

/**
 * Portable recipe artifact. Feature SQL, transforms, model class, params, and metadata.
 */
export type AutoresearchModelApiModelRecipe = { [key: string]: unknown }

/**
 * Extended metrics bundle. Holds the holdout AUC from training, and under 'realized' the newest validated date's online metrics: realized AUC, Brier score, calibration error and bins, lift@k, average precision, confusion counts at top 10%, top 20% and Likely, base rate, and row counts.
 */
export type AutoresearchModelApiMetrics = { [key: string]: unknown }

export interface AutoresearchModelApi {
    /** Unique UUID of this model version. */
    readonly id: string
    /** Pipeline this model belongs to. */
    pipeline: string
    /** Model role: 'champion' (active scoring model), 'challenger' (shadow model), or 'archived'.
     *
     * * `champion` - Champion
     * * `challenger` - Challenger
     * * `archived` - Archived */
    role?: AutoresearchModelRoleEnumApi
    /** SHA-256 of the serialized recipe. Used to deduplicate identical recipes across runs. */
    readonly recipe_hash: string
    /** Portable recipe artifact. Feature SQL, transforms, model class, params, and metadata. */
    model_recipe: AutoresearchModelApiModelRecipe
    /** Global feature importance and directionality. Used to explain top drivers on the model card. */
    model_explanation: ModelExplanationFieldApi
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
    /** Extended metrics bundle. Holds the holdout AUC from training, and under 'realized' the newest validated date's online metrics: realized AUC, Brier score, calibration error and bins, lift@k, average precision, confusion counts at top 10%, top 20% and Likely, base rate, and row counts. */
    metrics?: AutoresearchModelApiMetrics
    /**
     * Training run that produced this model. Read that run's artifact bundle to reuse the champion's train.py and features.sql as a starting point. Null for legacy models.
     * @nullable
     */
    readonly source_training_run: string | null
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
    /** True if this model is in the pipeline's shadow set: the champion, the previous champion, and up to 3 recent fitted challengers with distinct recipes. */
    readonly in_shadow_set: boolean
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
 * * `validation` - Validation
 * * `property_cleanup` - Property cleanup
 */
export type AutoresearchRunRunTypeEnumApi =
    (typeof AutoresearchRunRunTypeEnumApi)[keyof typeof AutoresearchRunRunTypeEnumApi]

export const AutoresearchRunRunTypeEnumApi = {
    Inference: 'inference',
    Validation: 'validation',
    PropertyCleanup: 'property_cleanup',
} as const

/**
 * * `pending` - Pending
 * * `running` - Running
 * * `completed` - Completed
 * * `failed` - Failed
 */
export type ZendeskImportJobStatusEnumApi =
    (typeof ZendeskImportJobStatusEnumApi)[keyof typeof ZendeskImportJobStatusEnumApi]

export const ZendeskImportJobStatusEnumApi = {
    Pending: 'pending',
    Running: 'running',
    Completed: 'completed',
    Failed: 'failed',
} as const

/**
 * Run metrics: score distribution summary, validation AUC, etc. An inference run records 'rows_eligible', the users in the inference population. When it is larger than rows_scored, the run scored a rolling part of the population: users never scored first, then users whose last score was oldest.
 */
export type AutoresearchRunApiMetrics = { [key: string]: unknown }

export interface AutoresearchRunApi {
    /** Unique UUID of this run. */
    readonly id: string
    /** Pipeline this run belongs to. */
    pipeline: string
    /**
     * Model used for scoring. Null for validation runs.
     * @nullable
     */
    model?: string | null
    /** Type of run: 'inference' (daily scoring) or 'validation' (outcome evaluation).
     *
     * * `inference` - Inference
     * * `validation` - Validation
     * * `property_cleanup` - Property cleanup */
    run_type: AutoresearchRunRunTypeEnumApi
    /** Run status: pending, running, completed, or failed.
     *
     * * `pending` - Pending
     * * `running` - Running
     * * `completed` - Completed
     * * `failed` - Failed */
    status?: ZendeskImportJobStatusEnumApi
    /**
     * Number of users scored in this inference run.
     * @minimum -2147483648
     * @maximum 2147483647
     * @nullable
     */
    rows_scored?: number | null
    /** Run metrics: score distribution summary, validation AUC, etc. An inference run records 'rows_eligible', the users in the inference population. When it is larger than rows_scored, the run scored a rolling part of the population: users never scored first, then users whose last score was oldest. */
    metrics: AutoresearchRunApiMetrics
    /** Score coverage and score age at the cutoff of a live champion run. Null for backfill, shadow, validation and older runs. */
    readonly coverage: AutoresearchPredictionCoverageApi | null
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
 * * `consider` - Consider
 */
export type AutoresearchSuggestionPriorityEnumApi =
    (typeof AutoresearchSuggestionPriorityEnumApi)[keyof typeof AutoresearchSuggestionPriorityEnumApi]

export const AutoresearchSuggestionPriorityEnumApi = {
    TryNext: 'try_next',
    Consider: 'consider',
} as const

/**
 * * `queued` - Queued
 * * `picked_up` - Picked up
 * * `acted_on` - Acted on
 * * `dismissed` - Dismissed
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
 * * `agent` - Agent
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
     *
     * * `try_next` - Try next
     * * `consider` - Consider */
    priority?: AutoresearchSuggestionPriorityEnumApi
    /** Lifecycle status: 'queued' (awaiting pickup), 'picked_up' (agent is applying as a constraint), 'acted_on' (agent spawned iterations), 'dismissed' (agent rejected with rationale).
     *
     * * `queued` - Queued
     * * `picked_up` - Picked up
     * * `acted_on` - Acted on
     * * `dismissed` - Dismissed */
    readonly status: AutoresearchSuggestionStatusEnumApi
    /** 'user' for human-submitted suggestions; 'agent' for agent-generated hypotheses.
     *
     * * `user` - User
     * * `agent` - Agent */
    readonly source: AutoresearchSuggestionSourceEnumApi
    /** Agent's note on how the suggestion was interpreted and acted upon. Populated after pickup. */
    readonly agent_response: string
    /** The user who submitted it; null for an agent-authored suggestion. */
    readonly created_by: UserBasicApi | null
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
 * * `consider` - consider
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
     *
     * * `try_next` - try_next
     * * `consider` - consider */
    priority?: CreateSuggestionPriorityEnumApi
}

/**
 * * `picked_up` - picked_up
 * * `acted_on` - acted_on
 * * `dismissed` - dismissed
 */
export type RespondToSuggestionStatusEnumApi =
    (typeof RespondToSuggestionStatusEnumApi)[keyof typeof RespondToSuggestionStatusEnumApi]

export const RespondToSuggestionStatusEnumApi = {
    PickedUp: 'picked_up',
    ActedOn: 'acted_on',
    Dismissed: 'dismissed',
} as const

/**
 * Input for the agent to record how it interpreted a steering suggestion.
 */
export interface RespondToSuggestionApi {
    /** How the agent handled the suggestion: 'picked_up' (applied as a search constraint), 'acted_on' (spawned one or more iterations), or 'dismissed' (rejected — explain why in agent_response).
     *
     * * `picked_up` - picked_up
     * * `acted_on` - acted_on
     * * `dismissed` - dismissed */
    status: RespondToSuggestionStatusEnumApi
    /**
     * Plain-English note on how the suggestion was interpreted and acted upon. A dismissal needs a note, sent now or recorded earlier. Omit it to keep the note already recorded; send an empty string to clear it.
     * @maxLength 2000
     */
    agent_response?: string
}

/**
 * * `explore` - Explore
 * * `scheduled` - Scheduled
 * * `rescue` - Rescue
 * * `manual` - Manual
 */
export type AutoresearchTrainingRunKickoffReasonEnumApi =
    (typeof AutoresearchTrainingRunKickoffReasonEnumApi)[keyof typeof AutoresearchTrainingRunKickoffReasonEnumApi]

export const AutoresearchTrainingRunKickoffReasonEnumApi = {
    Explore: 'explore',
    Scheduled: 'scheduled',
    Rescue: 'rescue',
    Manual: 'manual',
} as const

/**
 * One iteration referenced from a run summary's ladder or dead-ends list.
 */
export interface TrainingRunSummaryLadderItemApi {
    /** Iteration index this entry refers to. */
    iteration_number: number
    /**
     * Holdout AUC for this iteration.
     * @nullable
     */
    holdout_score: number | null
    /** Model class tried in this iteration. */
    model_class: string
    /** The agent's rationale for this attempt. */
    agent_description: string
}

/**
 * Tier-1 distilled summary of a completed run — the orientation memory a new run reads first.
 */
export interface TrainingRunSummaryApi {
    /** Target event the run's pipeline predicts. */
    target_event: string
    /** Prediction horizon, in days. */
    horizon_days: number
    /**
     * Best holdout AUC achieved in the run.
     * @nullable
     */
    best_holdout_score: number | null
    /** Whether this run's best model was promoted to champion (vs kept as challenger). */
    champion_promoted: boolean
    /** Model class of the run's best model. */
    champion_model_class: string
    /** Kept iterations, highest holdout AUC first — the winning approaches worth reusing. */
    kept_ladder: TrainingRunSummaryLadderItemApi[]
    /** Discarded or crashed iterations — approaches already tried that did not help; avoid repeating. */
    dead_ends: TrainingRunSummaryLadderItemApi[]
    /** Agent's suggested next experiments for a future run. Empty if not provided. */
    recommended_next: string
    /** Agent's 1–2 sentence distillation of what this run learned. Empty if not provided. */
    distillation: string
    /** Short id of the report notebook the agent built for this run. Empty if there is none. */
    report_notebook_short_id?: string
}

/**
 * * `kept` - Kept
 * * `discarded` - Discarded
 * * `crashed` - Crashed
 */
export type AutoresearchIterationStatusEnumApi =
    (typeof AutoresearchIterationStatusEnumApi)[keyof typeof AutoresearchIterationStatusEnumApi]

export const AutoresearchIterationStatusEnumApi = {
    Kept: 'kept',
    Discarded: 'discarded',
    Crashed: 'crashed',
} as const

/**
 * Keyword arguments for the estimator's constructor; null or absent means the defaults.
 * @nullable
 */
export type IterationTrailApiModelSpecModelParams = { [key: string]: unknown } | null

/**
 * Model class and hyperparameters tried in this iteration.
 */
export type IterationTrailApiModelSpec = {
    /** Dotted path of the estimator class. */
    model_class: string
    /**
     * Keyword arguments for the estimator's constructor; null or absent means the defaults.
     * @nullable
     */
    model_params?: IterationTrailApiModelSpecModelParams
}

/**
 * Compact, read-only view of one iteration for the cross-run history feed and the Training tab.
 */
export interface IterationTrailApi {
    /**
     * Order of this attempt within its run (0-based).
     * @minimum -2147483648
     * @maximum 2147483647
     */
    iteration_number: number
    /** Whether this recipe was kept (improved the best score), discarded, or crashed.
     *
     * * `kept` - Kept
     * * `discarded` - Discarded
     * * `crashed` - Crashed */
    status: AutoresearchIterationStatusEnumApi
    /**
     * Holdout AUC this iteration achieved. Null if it was skipped/degenerate.
     * @nullable
     */
    holdout_score?: number | null
    /**
     * Train-fold AUC for this iteration, if recorded.
     * @nullable
     */
    train_score?: number | null
    /** The agent's one-line rationale for what it tried and why. */
    agent_description?: string
    /**
     * Plain-language sentence on what this experiment tried and what happened, for people. Null if not written.
     * @nullable
     */
    readonly summary: string | null
    /**
     * Short title for this experiment, for people. Null if not written.
     * @nullable
     */
    readonly headline: string | null
    /** Model class and hyperparameters tried in this iteration. */
    model_spec: IterationTrailApiModelSpec
}

export interface AutoresearchTrainingRunApi {
    /** Unique UUID of this training run. */
    readonly id: string
    /** Pipeline this training run belongs to. */
    pipeline: string
    /**
     * Parent Task ID in the tasks sandbox. Null for stub runs.
     * @nullable
     */
    task_id?: string | null
    /**
     * Task sandbox run ID. Null for stub/synchronous training runs.
     * @nullable
     */
    task_run_id?: string | null
    /**
     * Relative URL to the underlying sandbox Task detail page. Null for stub/synchronous training runs.
     * @nullable
     */
    readonly task_url: string | null
    /** Run status: pending, running, completed, or failed.
     *
     * * `pending` - Pending
     * * `running` - Running
     * * `completed` - Completed
     * * `failed` - Failed */
    readonly status: ZendeskImportJobStatusEnumApi
    /** Why the run started: explore (the first burst of daily runs), scheduled (the research interval), rescue (the champion cannot score) or manual (a person or an agent asked). Null for older runs.
     *
     * * `explore` - Explore
     * * `scheduled` - Scheduled
     * * `rescue` - Rescue
     * * `manual` - Manual */
    readonly kickoff_reason: AutoresearchTrainingRunKickoffReasonEnumApi | null
    /**
     * Runtime that drove the training agent, 'claude' or 'codex'. Null for older runs and runs with no task.
     * @nullable
     */
    readonly agent_runtime_adapter: string | null
    /**
     * Model the training agent ran on. Null for older runs and runs with no task.
     * @nullable
     */
    readonly agent_model: string | null
    /**
     * Display name of agent_model, e.g. 'Claude Opus 5.5'. Null when agent_model is null.
     * @nullable
     */
    readonly agent_model_label: string | null
    /**
     * Reasoning effort the training agent ran at. Null for older runs, runs with no task, and models with no effort setting.
     * @nullable
     */
    readonly agent_reasoning_effort: string | null
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
    /** Distilled cross-run learning summary written on completion. Null until the run completes. */
    readonly summary: TrainingRunSummaryApi | null
    /**
     * One or two plain sentences on what this run learned, for people. Null if not written.
     * @nullable
     */
    readonly reader_summary: string | null
    /**
     * Short title for this run, for people. Null if not written.
     * @nullable
     */
    readonly headline: string | null
    /**
     * Short plain-language next steps for people, at most 5. Null if not written.
     * @nullable
     */
    readonly next_steps: readonly string[] | null
    /** Per-iteration breakdown — every recipe the agent tried this run, kept or discarded, with its model spec, holdout/train AUC, and one-line rationale. Ordered by iteration_number. */
    readonly iterations: readonly IterationTrailApi[]
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
 * Input for opening an agent-driven training run.
 */
export interface OpenTrainingRunApi {
    /**
     * Iteration budget for this run. Defaults to the pipeline's iterations_per_run if omitted.
     * @minimum 1
     * @maximum 500
     */
    iteration_budget?: number
}

/**
 * The relative paths present in a training run's bundle.
 */
export interface ArtifactListApi {
    /** Relative paths of every file stored under this training run's bundle prefix. */
    paths: string[]
    /** Number of files in the bundle. */
    count: number
}

/**
 * Input for fetching or deleting one bundle file by path.
 */
export interface ArtifactPathApi {
    /**
     * Relative path of the file within the bundle, e.g. 'train.py'.
     * @maxLength 500
     */
    path: string
}

/**
 * Whether a delete removed an existing file.
 */
export interface ArtifactDeleteResultApi {
    /** Relative path targeted for deletion. */
    path: string
    /** True if a file existed and was removed; False if nothing was there. */
    deleted: boolean
}

/**
 * A single bundle file's content, base64-encoded.
 */
export interface ArtifactContentApi {
    /** Relative path of the file within the bundle. */
    path: string
    /** File size in bytes. */
    size_bytes: number
    /** SHA-256 hex digest of the file content. */
    sha256: string
    /** File contents, base64-encoded. */
    content_base64: string
}

/**
 * Input for uploading one file of a training run's artifact bundle.
 */
export interface ArtifactUploadApi {
    /**
     * Relative path within the bundle, e.g. 'train.py', 'predict.py', 'features.sql', or 'eda/iter-3-gbm.ipynb'. Segments are limited to [A-Za-z0-9_.-]; absolute paths and '..' traversal are rejected.
     * @maxLength 500
     */
    path: string
    /** File contents, base64-encoded. Decoded server-side and written to object storage. Max 10 MB decoded. */
    content_base64: string
}

/**
 * Result of an upload: where the file landed and its content hash.
 */
export interface StoredArtifactApi {
    /** Relative path the file was stored at. */
    path: string
    /** Decoded file size in bytes. */
    size_bytes: number
    /** SHA-256 hex digest of the decoded file content. */
    sha256: string
}

/**
 * Input for finalizing a training run. The backend selects/promotes the champion.
 */
export interface CompleteTrainingRunApi {
    /**
     * Advisory nomination. The server promotes the kept iteration with the highest holdout_score; this id only breaks a tie at that score, and a lower-scoring nomination is logged and ignored.
     * @nullable
     */
    best_iteration_id?: string | null
    /** Global feature importance / directionality bundle for the champion model card. */
    model_explanation?: ModelExplanationFieldApi
    /**
     * What a future run should try next, given what this run learned. Stored in the run summary so the next run reads it during orientation. Keep it short and concrete; max 2000 characters.
     * @maxLength 2000
     */
    recommended_next?: string
    /**
     * A 1–2 sentence distillation of what this run learned — the winning signal, the key transform, the dead-ends. Stored in the run summary as the cheapest thing the next run reads. Max 2000 characters.
     * @maxLength 2000
     */
    distillation?: string
    /**
     * One or two plain sentences for people on what this run learned. Max 600 characters.
     * @maxLength 600
     * @nullable
     */
    reader_summary?: string | null
    /**
     * A short title for people, at most 60 characters, on what this run learned. Use plain words, with no column names, SQL or model jargon. Longer text is cut, not rejected.
     * @nullable
     */
    headline?: string | null
    /**
     * Short next steps for people, at most 5 items of a few words each (max 80 characters per item).
     * @maxItems 5
     * @nullable
     * @items.maxLength 80
     */
    next_steps?: string[] | null
    /** Short id of the report notebook you built for this run. Stored in the run summary only if the notebook exists in this project; an unknown id is dropped and does not fail the completion. */
    report_notebook_short_id?: string
}

export type RecordIterationApiRecipeSnapshotFeatureTransformsItem = { [key: string]: unknown }

/**
 * Compact recipe for this iteration: feature_sql (HogQL SELECT keyed on person_id) and transforms.
 */
export type RecordIterationApiRecipeSnapshot = {
    /** A read-only HogQL SELECT from {anchors}, one row per person, keyed on person_id. */
    feature_sql: string
    /**
     * Transforms the bundle applies to the feature columns; null or absent means none, and the in-process path accepts none.
     * @nullable
     */
    feature_transforms?: RecordIterationApiRecipeSnapshotFeatureTransformsItem[] | null
}

/**
 * Keyword arguments for the estimator's constructor; null or absent means the defaults.
 * @nullable
 */
export type RecordIterationApiModelSpecModelParams = { [key: string]: unknown } | null

/**
 * model_class and model_params tried this iteration. Any class is accepted here; the sklearn/xgboost allowlist applies at completion, to a run that uploaded no bundle.
 */
export type RecordIterationApiModelSpec = {
    /** Dotted path of the estimator class. */
    model_class: string
    /**
     * Keyword arguments for the estimator's constructor; null or absent means the defaults.
     * @nullable
     */
    model_params?: RecordIterationApiModelSpecModelParams
}

/**
 * * `kept` - kept
 * * `discarded` - discarded
 * * `crashed` - crashed
 */
export type RecordIterationStatusEnumApi =
    (typeof RecordIterationStatusEnumApi)[keyof typeof RecordIterationStatusEnumApi]

export const RecordIterationStatusEnumApi = {
    Kept: 'kept',
    Discarded: 'discarded',
    Crashed: 'crashed',
} as const

/**
 * Input for recording one training iteration. Validated against the recipe allowlist.
 */
export interface RecordIterationApi {
    /**
     * Zero-based index of this iteration within the run. Re-sending the same number updates that iteration (idempotent).
     * @minimum 0
     * @maximum 2147483647
     */
    iteration_number: number
    /** Compact recipe for this iteration: feature_sql (HogQL SELECT keyed on person_id) and transforms. */
    recipe_snapshot: RecordIterationApiRecipeSnapshot
    /** model_class and model_params tried this iteration. Any class is accepted here; the sklearn/xgboost allowlist applies at completion, to a run that uploaded no bundle. */
    model_spec: RecordIterationApiModelSpec
    /** 'kept' if this iteration improved on the best score, 'discarded' otherwise, 'crashed' on failure.
     *
     * * `kept` - kept
     * * `discarded` - discarded
     * * `crashed` - crashed */
    status: RecordIterationStatusEnumApi
    /**
     * Training-set AUC for this iteration (0-1).
     * @minimum 0
     * @maximum 1
     * @nullable
     */
    train_score?: number | null
    /**
     * Held-out AUC for this iteration (0-1). Used to pick the champion at completion.
     * @minimum 0
     * @maximum 1
     * @nullable
     */
    holdout_score?: number | null
    /**
     * Agent's plain-English rationale for this iteration. Max 2000 characters.
     * @maxLength 2000
     */
    agent_description?: string
    /**
     * One plain sentence for people on what this experiment tried and what happened. Max 300 characters.
     * @maxLength 300
     * @nullable
     */
    summary?: string | null
    /**
     * A short title for people, at most 60 characters, on what this experiment tried. Use plain words, with no column names, SQL or model jargon. Longer text is cut, not rejected.
     * @nullable
     */
    headline?: string | null
    /**
     * Agent's self-assessed confidence (0-1) that this iteration helps.
     * @minimum 0
     * @maximum 1
     * @nullable
     */
    agent_confidence?: number | null
    /**
     * UUID of the steering suggestion this iteration was spawned from, if any. Set it whenever the iteration acts on a pending suggestion — it links the iteration back to the suggestion for attribution and advances the suggestion to 'acted_on'.
     * @nullable
     */
    parent_suggestion?: string | null
}

export type AutoresearchIterationApiRecipeSnapshotFeatureTransformsItem = { [key: string]: unknown }

/**
 * Compact recipe snapshot at time of iteration. Full artifact lives in the model row.
 */
export type AutoresearchIterationApiRecipeSnapshot = {
    /** A read-only HogQL SELECT from {anchors}, one row per person, keyed on person_id. */
    feature_sql: string
    /**
     * Transforms the bundle applies to the feature columns; null or absent means none, and the in-process path accepts none.
     * @nullable
     */
    feature_transforms?: AutoresearchIterationApiRecipeSnapshotFeatureTransformsItem[] | null
}

/**
 * Keyword arguments for the estimator's constructor; null or absent means the defaults.
 * @nullable
 */
export type AutoresearchIterationApiModelSpecModelParams = { [key: string]: unknown } | null

/**
 * Model class and hyperparameters tried in this iteration.
 */
export type AutoresearchIterationApiModelSpec = {
    /** Dotted path of the estimator class. */
    model_class: string
    /**
     * Keyword arguments for the estimator's constructor; null or absent means the defaults.
     * @nullable
     */
    model_params?: AutoresearchIterationApiModelSpecModelParams
}

export interface AutoresearchIterationApi {
    readonly id: string
    pipeline: string
    training_run: string
    /**
     * @minimum -2147483648
     * @maximum 2147483647
     */
    iteration_number: number
    /** @maxLength 64 */
    recipe_hash: string
    /** Compact recipe snapshot at time of iteration. Full artifact lives in the model row. */
    recipe_snapshot: AutoresearchIterationApiRecipeSnapshot
    /** Model class and hyperparameters tried in this iteration. */
    model_spec: AutoresearchIterationApiModelSpec
    /** @nullable */
    train_score?: number | null
    /** @nullable */
    holdout_score?: number | null
    status: AutoresearchIterationStatusEnumApi
    agent_description?: string
    /**
     * Plain-language sentence on what this experiment tried and what happened, for people.
     * @nullable
     */
    summary?: string | null
    /**
     * Short title for this experiment, for people.
     * @nullable
     */
    headline?: string | null
    /**
     * Agent's self-assessed confidence 0–1
     * @nullable
     */
    agent_confidence?: number | null
    /**
     * UUID of the steering suggestion this iteration was spawned from, if any.
     * @nullable
     */
    parent_suggestion?: string | null
    readonly created_at: string
}

/**
 * Input for materializing the labeled training feature matrix into the run's sandbox.
 */
export interface MaterializeFeaturesRequestApi {
    /** Your HogQL feature query, using the {anchors}/{lookback_days} contract. Must be a read-only SELECT keyed on person_id (aliased to distinct_id), one row per user. The backend runs it server-side against the labeled training population — no 500-row cap — and writes the resulting train/holdout feature and label parquet files into your sandbox. */
    features_sql: string
}

/**
 * The local sandbox paths and shape of the materialized training matrix.
 */
export interface MaterializeFeaturesResponseApi {
    /** Sandbox path to the training feature matrix parquet (distinct_id + numeric feature columns). */
    train_features_path: string
    /** Sandbox path to the training labels parquet (distinct_id + __label). */
    train_labels_path: string
    /** Sandbox path to the holdout feature matrix parquet (same columns as train_features). */
    holdout_features_path: string
    /** Sandbox path to the holdout labels parquet (distinct_id + __label). */
    holdout_labels_path: string
    /** Number of rows in the training split. */
    n_train: number
    /** Number of rows in the holdout split. */
    n_holdout: number
    /** Number of numeric feature columns produced by features_sql. */
    n_features: number
    /** The numeric feature column names (excludes distinct_id, __label, __fold). */
    feature_cols: string[]
    /** Seconds the server spent on the queries that materialized the matrix. Scoring runs features_sql over the whole inference population on every cadence, so a slow query here is slow there too. */
    elapsed_s: number
    /** Rows ClickHouse read to materialize the matrix. */
    rows_read: number
    /** Advice on the cost of features_sql. A hint does not block the materialization or the upload, but a champion whose features.sql cannot score today's population in time is not promoted. */
    hints: string[]
}

/**
 * Keyword arguments for the estimator's constructor; null or absent means the defaults.
 * @nullable
 */
export type IterationTrailWithRecipeApiModelSpecModelParams = { [key: string]: unknown } | null

/**
 * Model class and hyperparameters tried in this iteration.
 */
export type IterationTrailWithRecipeApiModelSpec = {
    /** Dotted path of the estimator class. */
    model_class: string
    /**
     * Keyword arguments for the estimator's constructor; null or absent means the defaults.
     * @nullable
     */
    model_params?: IterationTrailWithRecipeApiModelSpecModelParams
}

export type IterationTrailWithRecipeApiRecipeSnapshotFeatureTransformsItem = { [key: string]: unknown }

/**
 * The recipe this iteration tried: its feature_sql and transforms, so a later run can reuse them.
 */
export type IterationTrailWithRecipeApiRecipeSnapshot = {
    /** A read-only HogQL SELECT from {anchors}, one row per person, keyed on person_id. */
    feature_sql: string
    /**
     * Transforms the bundle applies to the feature columns; null or absent means none, and the in-process path accepts none.
     * @nullable
     */
    feature_transforms?: IterationTrailWithRecipeApiRecipeSnapshotFeatureTransformsItem[] | null
}

/**
 * The trail with each iteration's recipe, for history only: a run list page would otherwise carry every recipe of every run.
 */
export interface IterationTrailWithRecipeApi {
    /**
     * Order of this attempt within its run (0-based).
     * @minimum -2147483648
     * @maximum 2147483647
     */
    iteration_number: number
    /** Whether this recipe was kept (improved the best score), discarded, or crashed.
     *
     * * `kept` - Kept
     * * `discarded` - Discarded
     * * `crashed` - Crashed */
    status: AutoresearchIterationStatusEnumApi
    /**
     * Holdout AUC this iteration achieved. Null if it was skipped/degenerate.
     * @nullable
     */
    holdout_score?: number | null
    /**
     * Train-fold AUC for this iteration, if recorded.
     * @nullable
     */
    train_score?: number | null
    /** The agent's one-line rationale for what it tried and why. */
    agent_description?: string
    /**
     * Plain-language sentence on what this experiment tried and what happened, for people. Null if not written.
     * @nullable
     */
    readonly summary: string | null
    /**
     * Short title for this experiment, for people. Null if not written.
     * @nullable
     */
    readonly headline: string | null
    /** Model class and hyperparameters tried in this iteration. */
    model_spec: IterationTrailWithRecipeApiModelSpec
    /** The recipe this iteration tried: its feature_sql and transforms, so a later run can reuse them. */
    recipe_snapshot: IterationTrailWithRecipeApiRecipeSnapshot
}

/**
 * One prior completed training run plus its full iteration trail.
 */
export interface TrainingRunHistoryEntryApi {
    /** UUID of the completed training run. */
    run_id: string
    /** UUID of the pipeline this run belongs to. */
    pipeline_id: string
    /** True if this run is from the pipeline you are training; False if it is a same-target sibling pipeline on the team. */
    is_current_pipeline: boolean
    /** Target event this run's pipeline predicts. */
    target_event: string
    /** Prediction horizon (days) of this run's pipeline. */
    horizon_days: number
    /**
     * Best holdout AUC achieved across this run's iterations.
     * @nullable
     */
    best_holdout_score: number | null
    /** Number of iterations recorded in this run. */
    iteration_count: number
    /**
     * When this run completed.
     * @nullable
     */
    completed_at: string | null
    /** Distilled tier-1 summary of this run — read this first to orient. Null for older runs without one. */
    summary: TrainingRunSummaryApi | null
    /** The iteration trail: every recipe tried, kept or discarded, with rationale and score. */
    iterations: IterationTrailWithRecipeApi[]
}

/**
 * Cross-run learning memory: prior runs the agent should read before iterating.
 */
export interface TrainingRunHistoryApi {
    /** Recent completed training runs — the current pipeline first, then same-target sibling pipelines on the team — newest first. Mine these to reuse winning features and avoid repeating discarded approaches. */
    runs: TrainingRunHistoryEntryApi[]
}

/**
 * Omit (or pass {"type": "event"}) to predict target_event; pass {"type": "action", "action_id": N} to predict a PostHog action. No other shapes are accepted.
 */
export type PatchedAutoresearchPipelineCreateApiTargetDefinition =
    | {
          type: 'event'
      }
    | {
          type: 'action'
          /**
           * ID of the action to predict.
           * @minimum 1
           */
          action_id: number
      }

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
     * Deprecated: scheduled training no longer reads it. Use iterations_per_run.
     * @minimum 1
     * @maximum 500
     */
    iteration_budget?: number
    /**
     * Experiments the agent may try in each training run (1-50). Each experiment costs agent time and queries, so a higher value costs more per run. Scheduled runs and Train now use it. Default: 5.
     * @minimum 1
     * @maximum 50
     */
    iterations_per_run?: number
    /** Days between scheduled research runs once the first burst of daily runs ends: 7, 14, 30, 60 or 90. Null means only when asked: no scheduled research, so the only training cost comes from runs you start and from rescue runs for a model that cannot score. A shorter interval costs more. Default: 7.
     *
     * * `7` - 7
     * * `14` - 14
     * * `30` - 30
     * * `60` - 60
     * * `90` - 90 */
    research_interval_days?: ResearchIntervalDaysEnumApi | null
    /**
     * Model the training agent runs on, a model id from the PostHog Tasks catalogue such as 'claude-opus-5-5', 'claude-sonnet-5-5' or 'gpt-6.1-sol'. Null or omitted uses the autoresearch default, Claude Opus 5.5. A larger model costs more per training run. Scheduled runs and Train now use it.
     * @maxLength 100
     * @nullable
     */
    agent_model?: string | null
    /**
     * Reasoning effort for the training agent, such as 'low', 'medium' or 'high'. It must be one the model supports, and without agent_model it is checked against the default model. Null or omitted uses the autoresearch default, medium. Higher effort costs more per training run.
     * @maxLength 20
     * @nullable
     */
    agent_reasoning_effort?: string | null
    /**
     * Target AUC threshold (0-1). Training stops early if reached. Default: 0.75.
     * @minimum 0
     * @maximum 1
     * @nullable
     */
    success_auc?: number | null
    /**
     * Stop training if no improvement in this many consecutive iterations (at least 1). Default: 10.
     * @minimum 1
     * @maximum 2147483647
     */
    plateau_iterations?: number
    /**
     * Person property name for the prediction score, e.g. 'predicted_p_pageview'. Auto-derived from target_event if omitted. Letters, digits, and _ $ . - only, and it cannot start with $ (reserved for PostHog's own properties); must be unique among this project's non-archived pipelines.
     * @maxLength 255
     */
    output_person_property?: string
    /** Write the champion's score to output_person_property on each scored person at every live scoring run. Default: false. Needed to target people by score in feature flags, cohorts, workflows and insights. Prediction events, validation and segments work without it. Turning it off, or archiving or deleting the pipeline while it is on, removes the property from the people it scored. */
    write_person_property?: boolean
}

export interface ConfusionCountsApi {
    /** True positives: flagged users who did the target event. */
    tp: number
    /** False positives: flagged users who did not do the target event. */
    fp: number
    /** False negatives: users not flagged who did the target event. */
    fn: number
    /** True negatives: users not flagged who did not do the target event. */
    tn: number
    /** Number of users the cutoff flagged (tp + fp). Top-k cutoffs flag every user tied at the boundary score, so this can be a little above k. */
    n_flagged: number
    /**
     * tp / n_flagged: share of flagged users who did the target event. Null when no user was flagged.
     * @nullable
     */
    precision: number | null
    /**
     * tp / (tp + fn): share of users who did the target event that the cutoff flagged. Null when no user did it.
     * @nullable
     */
    recall: number | null
}

export interface ConfusionByCutoffApi {
    /** Counts when the top 10% of users by score are flagged. */
    top_10: ConfusionCountsApi
    /** Counts when the top 20% of users by score are flagged. */
    top_20: ConfusionCountsApi
    /** Counts when users in the Likely segment, with a score of likely_threshold or higher, are flagged. */
    likely: ConfusionCountsApi
}

export interface CalibrationBinApi {
    /** Number of scored users in this bin. */
    n: number
    /** Mean predicted probability of the users in this bin. */
    mean_p_y: number
    /** Fraction of the users in this bin who did the target event within the horizon. */
    positive_rate: number
}

export interface OnlinePerformanceRowApi {
    /** UUID of the validation run that recorded these metrics. */
    validation_run_id: string
    /** Date the predictions were made for (UTC). */
    prediction_date: string
    /** Prediction horizon, in days, the predictions were made under. */
    horizon_days: number
    /** ISO weekday of the prediction date: 1 is Monday and 7 is Sunday. Use it to find weekday effects. */
    weekday: number
    /** UUID of the model that emitted the predictions. */
    model_id: string
    /** Role the model had when it emitted the predictions: 'champion' or 'challenger'. */
    emitted_role: string
    /** Role the model has now: 'champion', 'challenger', 'archived', or 'deleted'. A former champion that a promotion archived keeps its rows. */
    current_role: string
    /** Number of users the model scored on this date. */
    n_scored: number
    /** Number of scored users who did the target event in the horizon. */
    n_positive: number
    /** Fraction of scored users who did the target event (n_positive / n_scored). */
    base_rate: number
    /**
     * Mean predicted probability. Compare it with base_rate: a higher value means the model over-predicts. Null for dates validated before this metric existed.
     * @nullable
     */
    mean_p_y: number | null
    /**
     * Realized ROC AUC against actual outcomes. Null when the date has one class only.
     * @nullable
     */
    realized_auc: number | null
    /**
     * Lower bound of the 95% AUC interval (Hanley-McNeil). Null when realized_auc is null.
     * @nullable
     */
    realized_auc_ci_low: number | null
    /**
     * Upper bound of the 95% AUC interval (Hanley-McNeil). Null when realized_auc is null.
     * @nullable
     */
    realized_auc_ci_high: number | null
    /**
     * Brier score. Lower is better.
     * @nullable
     */
    brier_score: number | null
    /**
     * Expected calibration error over 10 equal-width bins. Lower is better.
     * @nullable
     */
    calibration_error: number | null
    /**
     * Positives in the top 10% by score, relative to a random 10%.
     * @nullable
     */
    lift_at_10: number | null
    /**
     * Positives in the top 20% by score, relative to a random 20%.
     * @nullable
     */
    lift_at_20: number | null
    /**
     * Average precision: area under the precision-recall curve. Higher is better, and a random model scores about base_rate. Null when no scored user did the target event, or for dates validated before this metric existed.
     * @nullable
     */
    average_precision: number | null
    /** Confusion counts, precision and recall at three cutoffs: top 10%, top 20%, and the Likely segment. Null for dates validated before this metric existed. */
    confusion: ConfusionByCutoffApi | null
    /**
     * The Likely cut point the 'likely' confusion counts used for this date, from the base rate of the dates checked before it. Null when confusion is null.
     * @nullable
     */
    likely_threshold: number | null
    /**
     * Calibration table with up to 10 bins cut at score quantiles, lowest scores first. Users with equal scores share a bin, so heavy ties give fewer bins. Null for dates validated before this metric existed.
     * @nullable
     */
    calibration_bins: CalibrationBinApi[] | null
    /**
     * 'single_class_no_auc' when every scored user had the same outcome, otherwise null.
     * @nullable
     */
    warning: string | null
    /**
     * When the validation run completed.
     * @nullable
     */
    validated_at: string | null
}

/**
 * * `realized` - Realized
 * * `training` - Training
 * * `fixed` - Fixed
 */
export type BaseRateSourceEnumApi = (typeof BaseRateSourceEnumApi)[keyof typeof BaseRateSourceEnumApi]

export const BaseRateSourceEnumApi = {
    Realized: 'realized',
    Training: 'training',
    Fixed: 'fixed',
} as const

export interface PredictionSegmentThresholdsApi {
    /** Users with a score at or above this probability are in the Likely segment: likely_lift times the base rate, capped halfway between the base rate and 1. A fixed cut point when base_rate_source is fixed. */
    likely_threshold: number
    /** Users with a score at or above this probability and below likely_threshold are in the Possible segment, and users below it are Unlikely. Equal to base_rate, or a fixed cut point when base_rate_source is fixed. */
    possible_threshold: number
    /** How many times the base rate a score must reach to be in the Likely segment. */
    likely_lift: number
    /**
     * The base rate the cut points use. When base_rate_source is realized, the fraction of the champion's scored users who did the target event, pooled over the newest checked dates. When base_rate_source is training, the fraction of the champion's training population that did it. Null when base_rate_source is fixed.
     * @nullable
     */
    base_rate: number | null
    /** Number of checked prediction dates the base rate pools. */
    base_rate_dates: number
    /** Where the cut points come from. realized: the checked dates hold enough positives. training: no realized base rate yet, so the champion's training population sets it. fixed: neither is available, so fixed cut points apply.
     *
     * * `realized` - Realized
     * * `training` - Training
     * * `fixed` - Fixed */
    base_rate_source: BaseRateSourceEnumApi
    /**
     * The current champion's mean predicted probability over the checked dates it scored as champion. Null until those dates hold enough positives.
     * @nullable
     */
    champion_mean_p_y: number | null
    /**
     * The real rate of the target event over the same dates as champion_mean_p_y.
     * @nullable
     */
    champion_base_rate: number | null
    /** True when champion_mean_p_y is far above or below champion_base_rate. The scores are then not probabilities (for example after class weighting in train.py), so a score of likely_lift times the base rate does not mean the user is that many times as likely to convert. */
    scores_miscalibrated: boolean
}

export interface OnlinePerformanceApi {
    /** One row per model per validated prediction date, newest date first. Empty until a prediction horizon has elapsed and online validation has run. */
    rows: OnlinePerformanceRowApi[]
    /** The current cut points between the Likely, Possible and Unlikely segments, set by lift over the realized base rate. They do not depend on limit. */
    segment_thresholds: PredictionSegmentThresholdsApi
}

export interface StartTrainingRequestApi {
    /**
     * Iterations for this training run. Defaults to the pipeline's iterations_per_run.
     * @minimum 1
     * @maximum 500
     */
    iteration_budget?: number
}

export interface AgentReasoningEffortOptionApi {
    /** Effort id to pass as agent_reasoning_effort, e.g. 'medium'. */
    value: string
    /** Display name, e.g. 'Medium'. */
    label: string
}

export interface AgentModelOptionApi {
    /** Model id to pass as agent_model, e.g. 'claude-sonnet-5-5'. */
    model: string
    /** Display name, e.g. 'Claude Sonnet 5.5'. */
    label: string
    /** Runtime that drives the model: 'claude' or 'codex'. */
    runtime_adapter: string
    /** Reasoning efforts this model supports. Empty when it has no effort setting. */
    supported_efforts: AgentReasoningEffortOptionApi[]
    /**
     * Token price relative to Claude Sonnet 5, e.g. '2×'. Null when no rate is known.
     * @nullable
     */
    cost_multiplier: string | null
}

export interface AgentModelOptionsApi {
    /** Model a pipeline with a null agent_model trains on. */
    default_model: string
    /** Display name of default_model. */
    default_model_label: string
    /**
     * Reasoning effort a pipeline with a null agent_reasoning_effort trains at.
     * @nullable
     */
    default_reasoning_effort: string | null
    /** Models a pipeline may set as agent_model. */
    models: AgentModelOptionApi[]
}

/**
 * * `likely_active_soon` - Likely Active Soon
 * * `at_risk_of_inactivity` - At Risk Of Inactivity
 * * `return_after_first_use` - Return After First Use
 * * `feature_adoption` - Feature Adoption
 * * `repeat_key_behavior` - Repeat Key Behavior
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
    /** Template to resolve. The templates endpoint lists each one with its description. Required.
     *
     * * `likely_active_soon` - Likely Active Soon
     * * `at_risk_of_inactivity` - At Risk Of Inactivity
     * * `return_after_first_use` - Return After First Use
     * * `feature_adoption` - Feature Adoption
     * * `repeat_key_behavior` - Repeat Key Behavior */
    template_key: TemplateKeyEnumApi
    /** Event name to use as the prediction target. Required for 'feature_adoption' and 'repeat_key_behavior'. Optional override for activity-based templates ('likely_active_soon', 'at_risk_of_inactivity', 'return_after_first_use'); omit to use the auto-resolved event. To predict an action, create the pipeline with target_definition after resolving. */
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
    /** The template key that was resolved. Pass it back to re-resolve with a different target_event.
     *
     * * `likely_active_soon` - Likely Active Soon
     * * `at_risk_of_inactivity` - At Risk Of Inactivity
     * * `return_after_first_use` - Return After First Use
     * * `feature_adoption` - Feature Adoption
     * * `repeat_key_behavior` - Repeat Key Behavior */
    template_key: TemplateKeyEnumApi
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
    /** Training lookback in days, sized so the horizon leaves room for training examples. Pass as 'training_lookback_days' to autoresearch-create. */
    training_lookback_days: number
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
    /** Template identifier, e.g. 'likely_active_soon'. Pass to autoresearch-resolve-template-create.
     *
     * * `likely_active_soon` - Likely Active Soon
     * * `at_risk_of_inactivity` - At Risk Of Inactivity
     * * `return_after_first_use` - Return After First Use
     * * `feature_adoption` - Feature Adoption
     * * `repeat_key_behavior` - Repeat Key Behavior */
    key: TemplateKeyEnumApi
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

/**
 * Optional target definition. Pass {"type": "action", "action_id": N} to predict a PostHog action (multi-step / property / autocapture matcher) instead of a single event.
 */
export type ValidatePipelineRequestApiTargetDefinition =
    | {
          type: 'event'
      }
    | {
          type: 'action'
          /**
           * ID of the action to predict.
           * @minimum 1
           */
          action_id: number
      }

/**
 * Population filter for training examples. Use {} for all identified users.
 */
export type ValidatePipelineRequestApiTrainingPopulation = { [key: string]: unknown }

/**
 * Population filter for daily scoring. When omitted or empty, the training population is counted, as creation stores it.
 */
export type ValidatePipelineRequestApiInferencePopulation = { [key: string]: unknown }

export interface ValidatePipelineRequestApi {
    /** Event name to predict, e.g. '$pageview'. Must exist in the team's event schema. Omit when predicting an action target (pass target_definition instead). */
    target_event?: string
    /** Optional target definition. Pass {"type": "action", "action_id": N} to predict a PostHog action (multi-step / property / autocapture matcher) instead of a single event. */
    target_definition?: ValidatePipelineRequestApiTargetDefinition
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
    /** Population filter for daily scoring. When omitted or empty, the training population is counted, as creation stores it. */
    inference_population?: ValidatePipelineRequestApiInferencePopulation
}

/**
 * * `info` - info
 * * `warning` - warning
 * * `error` - error
 */
export type ValidationWarningSeverityEnumApi =
    (typeof ValidationWarningSeverityEnumApi)[keyof typeof ValidationWarningSeverityEnumApi]

export const ValidationWarningSeverityEnumApi = {
    Info: 'info',
    Warning: 'warning',
    Error: 'error',
} as const

export interface ValidationWarningApi {
    /** Machine-readable warning code. 'horizon_exceeds_lookback', and 'population_too_large' with severity 'error', mean a run would fail: fix the definition before creating. 'population_too_large' with severity 'info' means training uses a sample of the population, or each scoring run scores a rolling part of it: users never scored first, then users whose last score was oldest. 'low_volume', 'low_positives' and 'low_negatives' mean the data is too thin for a reliable model (severity 'error', advisory). 'moderate_volume', 'mostly_anonymous_population', 'extreme_imbalance' and 'near_universal' are severity 'warning'. */
    code: string
    /** Human-readable warning description. */
    message: string
    /** Severity level. 'error' means training would fail or the data is too thin for a reliable model; see 'code' for which. 'warning' is worth acknowledging. Creation enforces none of them.
     *
     * * `info` - info
     * * `warning` - warning
     * * `error` - error */
    severity: ValidationWarningSeverityEnumApi
}

export interface ValidatePipelineResponseApi {
    /** False when any warning has severity 'error'. Creation does not enforce it, but a definition with an 'error' 'population_too_large' or 'horizon_exceeds_lookback' cannot train. */
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
    /** List of validation warnings. Check 'severity' and 'code'. */
    warnings: ValidationWarningApi[]
    /**
     * Why validation did not run, or null when it did. A query error in the definition itself is passed through; any other failure is a generic message and the detail is logged.
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

export type AutoresearchTrainingRunsHistoryRetrieveParams = {
    /**
     * Maximum number of prior runs to return (default 5, at most 20).
     * @minimum 1
     * @maximum 20
     */
    limit?: number
}

export type AutoresearchOnlinePerformanceRetrieveParams = {
    /**
     * Maximum number of validated prediction dates to return, newest first (default 60, at most 180). Each date returns one row per model that emitted predictions on it.
     * @minimum 1
     * @maximum 180
     */
    limit?: number
}
