/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Manage autoresearch prediction pipelines.
 *
 * A pipeline defines a target event, population, and horizon. The autoresearch
 * training loop finds the best predictive recipe; the inference workflow scores
 * users daily and emits autoresearch_prediction events.
 */
export const autoresearchCreateBodyNameMax = 255

export const autoresearchCreateBodyTargetEventMax = 255

export const autoresearchCreateBodyHorizonDaysMax = 365

export const autoresearchCreateBodyTrainingLookbackDaysMin = 7
export const autoresearchCreateBodyTrainingLookbackDaysMax = 730

export const autoresearchCreateBodyCadenceDaysMax = 365

export const autoresearchCreateBodyIterationBudgetMax = 500

export const autoresearchCreateBodyPlateauIterationsMin = -2147483648
export const autoresearchCreateBodyPlateauIterationsMax = 2147483647

export const autoresearchCreateBodyOutputPersonPropertyMax = 255

export const AutoresearchCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(autoresearchCreateBodyNameMax).describe('Display name for the pipeline.'),
    description: zod.string().optional().describe('Optional free-text description.'),
    target_event: zod
        .string()
        .max(autoresearchCreateBodyTargetEventMax)
        .optional()
        .describe(
            "PostHog event name to predict, e.g. '$pageview' or 'signed_up'. Omit when predicting an action target (pass target_definition instead)."
        ),
    target_definition: zod
        .looseObject({})
        .optional()
        .describe(
            'Omit (or pass {\"type\": \"event\"}) to predict target_event; pass {\"type\": \"action\", \"action_id\": N} to predict a PostHog action. No other shapes are accepted.'
        ),
    horizon_days: zod
        .number()
        .min(1)
        .max(autoresearchCreateBodyHorizonDaysMax)
        .optional()
        .describe(
            'Prediction horizon in days (1-365). The model predicts whether the target event occurs within this window.'
        ),
    training_lookback_days: zod
        .number()
        .min(autoresearchCreateBodyTrainingLookbackDaysMin)
        .max(autoresearchCreateBodyTrainingLookbackDaysMax)
        .optional()
        .describe(
            'How far back to look for training examples (7-730 days). Larger windows give more data but may include stale behavior. Default: 180.'
        ),
    training_population: zod
        .looseObject({})
        .optional()
        .describe('Training population filter. Use {} for all identified users.'),
    inference_population: zod
        .looseObject({})
        .optional()
        .describe('Inference population filter. Defaults to training_population if not set.'),
    cadence_days: zod
        .number()
        .min(1)
        .max(autoresearchCreateBodyCadenceDaysMax)
        .optional()
        .describe('Re-score the inference population every N days (1-365). Default: 1.'),
    iteration_budget: zod
        .number()
        .min(1)
        .max(autoresearchCreateBodyIterationBudgetMax)
        .optional()
        .describe('Total training iterations allowed for the autoresearch loop (1-500). Default: 50.'),
    success_auc: zod
        .number()
        .nullish()
        .describe('Target AUC threshold. Training stops early if reached. Default: 0.75.'),
    plateau_iterations: zod
        .number()
        .min(autoresearchCreateBodyPlateauIterationsMin)
        .max(autoresearchCreateBodyPlateauIterationsMax)
        .optional()
        .describe('Stop training if no improvement in this many consecutive iterations. Default: 10.'),
    output_person_property: zod
        .string()
        .max(autoresearchCreateBodyOutputPersonPropertyMax)
        .optional()
        .describe(
            "Person property name for the prediction score, e.g. 'predicted_p_pageview'. Auto-derived from target_event if omitted. Letters, digits, and _ $ . - only; must be unique among this project's non-archived pipelines."
        ),
})

/**
 * Inject a free-text hypothesis or direction into a running pipeline. The sandbox agent reads queued suggestions at the start of each iteration batch and decides: translate into a concrete iteration ('acted_on'), apply as a search constraint ('picked_up'), or reject with rationale ('dismissed'). Use priority='try_next' to instruct the agent to act on this before autonomous iterations; 'consider' is advisory. Check 'agent_response' after the next training run to see how the suggestion was interpreted.
 * @summary Submit a suggestion
 */
export const autoresearchSuggestionsCreateBodyPromptMax = 2000

export const autoresearchSuggestionsCreateBodyPriorityDefault = `consider`

export const AutoresearchSuggestionsCreateBody = /* @__PURE__ */ zod.object({
    prompt: zod
        .string()
        .max(autoresearchSuggestionsCreateBodyPromptMax)
        .describe(
            "Free-text hypothesis or direction for the agent to explore, e.g. 'try a tree-based model' or 'remove recency features, I suspect leakage'."
        ),
    priority: zod
        .enum(['try_next', 'consider'])
        .describe('\* `try_next` - try_next\n\* `consider` - consider')
        .default(autoresearchSuggestionsCreateBodyPriorityDefault)
        .describe(
            "'try_next' asks the agent to act on this before other autonomous iterations; 'consider' is advisory context.\n\n\* `try_next` - try_next\n\* `consider` - consider"
        ),
})

/**
 * Record how the agent handled a steering suggestion: set status to 'picked_up' (applied as a search constraint), 'acted_on' (spawned iterations), or 'dismissed' (rejected — explain in agent_response), and write the agent_response note the human will read. Call this from the training loop after deciding what to do with a pending suggestion. Recording an iteration with parent_suggestion set already advances a suggestion to 'acted_on'; use this to add the narrative or to mark a suggestion picked_up/dismissed without spawning an iteration.
 * @summary Respond to a suggestion
 */
export const autoresearchSuggestionsRespondCreateBodyAgentResponseDefault = ``
export const autoresearchSuggestionsRespondCreateBodyAgentResponseMax = 2000

export const AutoresearchSuggestionsRespondCreateBody = /* @__PURE__ */ zod
    .object({
        status: zod
            .enum(['picked_up', 'acted_on', 'dismissed'])
            .describe('\* `picked_up` - picked_up\n\* `acted_on` - acted_on\n\* `dismissed` - dismissed')
            .describe(
                "How the agent handled the suggestion: 'picked_up' (applied as a search constraint), 'acted_on' (spawned one or more iterations), or 'dismissed' (rejected — explain why in agent_response).\n\n\* `picked_up` - picked_up\n\* `acted_on` - acted_on\n\* `dismissed` - dismissed"
            ),
        agent_response: zod
            .string()
            .max(autoresearchSuggestionsRespondCreateBodyAgentResponseMax)
            .default(autoresearchSuggestionsRespondCreateBodyAgentResponseDefault)
            .describe(
                'Plain-English note on how the suggestion was interpreted and acted upon (or why it was dismissed).'
            ),
    })
    .describe('Input for the agent to record how it interpreted a steering suggestion.')

/**
 * Open a new training run for a pipeline and return its id. An agent — the in-house sandbox, an external bring-your-own agent, or a scheduled job — then records iterations against this run and finalizes it with the complete endpoint. The run starts in 'running'.
 * @summary Open a training run
 */
export const autoresearchTrainingRunsCreateBodyIterationBudgetMax = 500

export const AutoresearchTrainingRunsCreateBody = /* @__PURE__ */ zod
    .object({
        iteration_budget: zod
            .number()
            .min(1)
            .max(autoresearchTrainingRunsCreateBodyIterationBudgetMax)
            .optional()
            .describe("Iteration budget for this run. Defaults to the pipeline's iteration_budget if omitted."),
    })
    .describe('Input for opening an agent-driven training run.')

/**
 * Remove one file from this training run's artifact bundle. Idempotent — deleting a missing file is a no-op. The bundle is frozen once the run completes or fails.
 * @summary Delete an artifact bundle file
 */
export const autoresearchTrainingRunsArtifactsDeleteCreateBodyPathMax = 500

export const AutoresearchTrainingRunsArtifactsDeleteCreateBody = /* @__PURE__ */ zod
    .object({
        path: zod
            .string()
            .max(autoresearchTrainingRunsArtifactsDeleteCreateBodyPathMax)
            .describe("Relative path of the file within the bundle, e.g. 'train.py'."),
    })
    .describe('Input for fetching or deleting one bundle file by path.')

/**
 * Fetch one file from this training run's artifact bundle, base64-encoded.
 * @summary Get an artifact bundle file
 */
export const autoresearchTrainingRunsArtifactsGetCreateBodyPathMax = 500

export const AutoresearchTrainingRunsArtifactsGetCreateBody = /* @__PURE__ */ zod
    .object({
        path: zod
            .string()
            .max(autoresearchTrainingRunsArtifactsGetCreateBodyPathMax)
            .describe("Relative path of the file within the bundle, e.g. 'train.py'."),
    })
    .describe('Input for fetching or deleting one bundle file by path.')

/**
 * Upload one file of this training run's artifact bundle. Send the file contents base64-encoded in content_base64. Re-uploading the same path overwrites it. Use this — not curl/set_output — to author train.py, predict.py, and features.sql. The bundle is frozen once the run completes or fails.
 * @summary Upload an artifact bundle file
 */
export const autoresearchTrainingRunsArtifactsUploadCreateBodyPathMax = 500

export const AutoresearchTrainingRunsArtifactsUploadCreateBody = /* @__PURE__ */ zod
    .object({
        path: zod
            .string()
            .max(autoresearchTrainingRunsArtifactsUploadCreateBodyPathMax)
            .describe(
                "Relative path within the bundle, e.g. 'train.py', 'predict.py', 'features.sql', or 'eda\/iter-3-gbm.ipynb'. Segments are limited to [A-Za-z0-9_.-]; absolute paths and '..' traversal are rejected."
            ),
        content_base64: zod
            .string()
            .describe(
                'File contents, base64-encoded. Decoded server-side and written to object storage. Max 10 MB decoded.'
            ),
    })
    .describe("Input for uploading one file of a training run's artifact bundle.")

/**
 * Finalize a training run. The backend selects the best iteration (highest holdout score, or the one you name), decides champion vs challenger via the promotion ladder, and persists the model. Agents cannot set the champion directly — promotion is server-side.
 * @summary Complete a training run
 */
export const autoresearchTrainingRunsCompleteCreateBodyRecommendedNextDefault = ``
export const autoresearchTrainingRunsCompleteCreateBodyRecommendedNextMax = 2000

export const autoresearchTrainingRunsCompleteCreateBodyDistillationDefault = ``
export const autoresearchTrainingRunsCompleteCreateBodyDistillationMax = 2000

export const AutoresearchTrainingRunsCompleteCreateBody = /* @__PURE__ */ zod
    .object({
        best_iteration_id: zod
            .uuid()
            .nullish()
            .describe(
                'Iteration to promote as champion candidate. If omitted, the kept iteration with the highest holdout_score is used.'
            ),
        model_explanation: zod
            .looseObject({})
            .optional()
            .describe('Global feature importance \/ directionality bundle for the champion model card.'),
        recommended_next: zod
            .string()
            .max(autoresearchTrainingRunsCompleteCreateBodyRecommendedNextMax)
            .default(autoresearchTrainingRunsCompleteCreateBodyRecommendedNextDefault)
            .describe(
                'What a future run should try next, given what this run learned. Stored in the run summary so the next run reads it during orientation. Keep it short and concrete; max 2000 characters.'
            ),
        distillation: zod
            .string()
            .max(autoresearchTrainingRunsCompleteCreateBodyDistillationMax)
            .default(autoresearchTrainingRunsCompleteCreateBodyDistillationDefault)
            .describe(
                'A 1–2 sentence distillation of what this run learned — the winning signal, the key transform, the dead-ends. Stored in the run summary as the cheapest thing the next run reads. Max 2000 characters.'
            ),
    })
    .describe('Input for finalizing a training run. The backend selects\/promotes the champion.')

/**
 * Record one iteration of an open training run. Idempotent on iteration_number — re-sending the same number updates that iteration. The recipe is validated server-side: model_class must be in the allowlist and feature_sql must be a read-only SELECT keyed on person_id.
 * @summary Record a training iteration
 */
export const autoresearchTrainingRunsIterationsCreateBodyIterationNumberMin = 0

export const autoresearchTrainingRunsIterationsCreateBodyTrainScoreMin = 0
export const autoresearchTrainingRunsIterationsCreateBodyTrainScoreMax = 1

export const autoresearchTrainingRunsIterationsCreateBodyHoldoutScoreMin = 0
export const autoresearchTrainingRunsIterationsCreateBodyHoldoutScoreMax = 1

export const autoresearchTrainingRunsIterationsCreateBodyAgentDescriptionDefault = ``
export const autoresearchTrainingRunsIterationsCreateBodyAgentConfidenceMin = 0
export const autoresearchTrainingRunsIterationsCreateBodyAgentConfidenceMax = 1

export const AutoresearchTrainingRunsIterationsCreateBody = /* @__PURE__ */ zod
    .object({
        iteration_number: zod
            .number()
            .min(autoresearchTrainingRunsIterationsCreateBodyIterationNumberMin)
            .describe(
                'Zero-based index of this iteration within the run. Re-sending the same number updates that iteration (idempotent).'
            ),
        recipe_snapshot: zod
            .looseObject({})
            .describe(
                'Compact recipe for this iteration: feature_sql (HogQL SELECT keyed on person_id) and transforms.'
            ),
        model_spec: zod
            .looseObject({})
            .describe('model_class (must be allowlisted) and model_params tried this iteration.'),
        status: zod
            .enum(['kept', 'discarded', 'crashed'])
            .describe('\* `kept` - kept\n\* `discarded` - discarded\n\* `crashed` - crashed')
            .describe(
                "'kept' if this iteration improved on the best score, 'discarded' otherwise, 'crashed' on failure.\n\n\* `kept` - kept\n\* `discarded` - discarded\n\* `crashed` - crashed"
            ),
        train_score: zod
            .number()
            .min(autoresearchTrainingRunsIterationsCreateBodyTrainScoreMin)
            .max(autoresearchTrainingRunsIterationsCreateBodyTrainScoreMax)
            .nullish()
            .describe('Training-set AUC for this iteration (0-1).'),
        holdout_score: zod
            .number()
            .min(autoresearchTrainingRunsIterationsCreateBodyHoldoutScoreMin)
            .max(autoresearchTrainingRunsIterationsCreateBodyHoldoutScoreMax)
            .nullish()
            .describe('Held-out AUC for this iteration (0-1). Used to pick the champion at completion.'),
        agent_description: zod
            .string()
            .default(autoresearchTrainingRunsIterationsCreateBodyAgentDescriptionDefault)
            .describe("Agent's plain-English rationale for this iteration."),
        agent_confidence: zod
            .number()
            .min(autoresearchTrainingRunsIterationsCreateBodyAgentConfidenceMin)
            .max(autoresearchTrainingRunsIterationsCreateBodyAgentConfidenceMax)
            .nullish()
            .describe("Agent's self-assessed confidence (0–1) that this iteration helps."),
        parent_suggestion: zod
            .uuid()
            .nullish()
            .describe(
                "UUID of the steering suggestion this iteration was spawned from, if any. Set it whenever the iteration acts on a pending suggestion — it links the iteration back to the suggestion for attribution and advances the suggestion to 'acted_on'."
            ),
    })
    .describe('Input for recording one training iteration. Validated against the recipe allowlist.')

/**
 * Run features_sql server-side against the labeled training population and write the resulting train/holdout feature and label parquet files directly into this run's sandbox. Returns the local sandbox paths, row counts, and feature columns. The rows never pass through the agent's context and there is no 500-row cap. Read the returned paths with pd.read_parquet and iterate in Python.
 * @summary Materialize training features to the sandbox
 */
export const AutoresearchTrainingRunsMaterializeFeaturesCreateBody = /* @__PURE__ */ zod
    .object({
        features_sql: zod
            .string()
            .describe(
                'Your HogQL feature query, using the {anchors}\/{lookback_days} contract. Must be a read-only SELECT keyed on person_id (aliased to distinct_id), one row per user. The backend runs it server-side against the labeled training population — no 500-row cap — and writes the resulting train\/holdout feature and label parquet files into your sandbox.'
            ),
    })
    .describe("Input for materializing the labeled training feature matrix into the run's sandbox.")

/**
 * Manage autoresearch prediction pipelines.
 *
 * A pipeline defines a target event, population, and horizon. The autoresearch
 * training loop finds the best predictive recipe; the inference workflow scores
 * users daily and emits autoresearch_prediction events.
 */
export const autoresearchUpdateBodyNameMax = 255

export const autoresearchUpdateBodyTargetEventMax = 255

export const autoresearchUpdateBodyHorizonDaysMax = 365

export const autoresearchUpdateBodyTrainingLookbackDaysMin = 7
export const autoresearchUpdateBodyTrainingLookbackDaysMax = 730

export const autoresearchUpdateBodyCadenceDaysMax = 365

export const autoresearchUpdateBodyIterationBudgetMax = 500

export const autoresearchUpdateBodyPlateauIterationsMin = -2147483648
export const autoresearchUpdateBodyPlateauIterationsMax = 2147483647

export const autoresearchUpdateBodyOutputPersonPropertyMax = 255

export const AutoresearchUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(autoresearchUpdateBodyNameMax).describe('Display name for the pipeline.'),
    description: zod.string().optional().describe('Optional free-text description.'),
    target_event: zod
        .string()
        .max(autoresearchUpdateBodyTargetEventMax)
        .optional()
        .describe(
            "PostHog event name to predict, e.g. '$pageview' or 'signed_up'. Omit when predicting an action target (pass target_definition instead)."
        ),
    target_definition: zod
        .looseObject({})
        .optional()
        .describe(
            'Omit (or pass {\"type\": \"event\"}) to predict target_event; pass {\"type\": \"action\", \"action_id\": N} to predict a PostHog action. No other shapes are accepted.'
        ),
    horizon_days: zod
        .number()
        .min(1)
        .max(autoresearchUpdateBodyHorizonDaysMax)
        .optional()
        .describe(
            'Prediction horizon in days (1-365). The model predicts whether the target event occurs within this window.'
        ),
    training_lookback_days: zod
        .number()
        .min(autoresearchUpdateBodyTrainingLookbackDaysMin)
        .max(autoresearchUpdateBodyTrainingLookbackDaysMax)
        .optional()
        .describe(
            'How far back to look for training examples (7-730 days). Larger windows give more data but may include stale behavior. Default: 180.'
        ),
    training_population: zod
        .looseObject({})
        .optional()
        .describe('Training population filter. Use {} for all identified users.'),
    inference_population: zod
        .looseObject({})
        .optional()
        .describe('Inference population filter. Defaults to training_population if not set.'),
    cadence_days: zod
        .number()
        .min(1)
        .max(autoresearchUpdateBodyCadenceDaysMax)
        .optional()
        .describe('Re-score the inference population every N days (1-365). Default: 1.'),
    iteration_budget: zod
        .number()
        .min(1)
        .max(autoresearchUpdateBodyIterationBudgetMax)
        .optional()
        .describe('Total training iterations allowed for the autoresearch loop (1-500). Default: 50.'),
    success_auc: zod
        .number()
        .nullish()
        .describe('Target AUC threshold. Training stops early if reached. Default: 0.75.'),
    plateau_iterations: zod
        .number()
        .min(autoresearchUpdateBodyPlateauIterationsMin)
        .max(autoresearchUpdateBodyPlateauIterationsMax)
        .optional()
        .describe('Stop training if no improvement in this many consecutive iterations. Default: 10.'),
    output_person_property: zod
        .string()
        .max(autoresearchUpdateBodyOutputPersonPropertyMax)
        .optional()
        .describe(
            "Person property name for the prediction score, e.g. 'predicted_p_pageview'. Auto-derived from target_event if omitted. Letters, digits, and _ $ . - only; must be unique among this project's non-archived pipelines."
        ),
})

/**
 * Manage autoresearch prediction pipelines.
 *
 * A pipeline defines a target event, population, and horizon. The autoresearch
 * training loop finds the best predictive recipe; the inference workflow scores
 * users daily and emits autoresearch_prediction events.
 */
export const autoresearchPartialUpdateBodyNameMax = 255

export const autoresearchPartialUpdateBodyTargetEventMax = 255

export const autoresearchPartialUpdateBodyHorizonDaysMax = 365

export const autoresearchPartialUpdateBodyTrainingLookbackDaysMin = 7
export const autoresearchPartialUpdateBodyTrainingLookbackDaysMax = 730

export const autoresearchPartialUpdateBodyCadenceDaysMax = 365

export const autoresearchPartialUpdateBodyIterationBudgetMax = 500

export const autoresearchPartialUpdateBodyPlateauIterationsMin = -2147483648
export const autoresearchPartialUpdateBodyPlateauIterationsMax = 2147483647

export const autoresearchPartialUpdateBodyOutputPersonPropertyMax = 255

export const AutoresearchPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(autoresearchPartialUpdateBodyNameMax).optional().describe('Display name for the pipeline.'),
    description: zod.string().optional().describe('Optional free-text description.'),
    target_event: zod
        .string()
        .max(autoresearchPartialUpdateBodyTargetEventMax)
        .optional()
        .describe(
            "PostHog event name to predict, e.g. '$pageview' or 'signed_up'. Omit when predicting an action target (pass target_definition instead)."
        ),
    target_definition: zod
        .looseObject({})
        .optional()
        .describe(
            'Omit (or pass {\"type\": \"event\"}) to predict target_event; pass {\"type\": \"action\", \"action_id\": N} to predict a PostHog action. No other shapes are accepted.'
        ),
    horizon_days: zod
        .number()
        .min(1)
        .max(autoresearchPartialUpdateBodyHorizonDaysMax)
        .optional()
        .describe(
            'Prediction horizon in days (1-365). The model predicts whether the target event occurs within this window.'
        ),
    training_lookback_days: zod
        .number()
        .min(autoresearchPartialUpdateBodyTrainingLookbackDaysMin)
        .max(autoresearchPartialUpdateBodyTrainingLookbackDaysMax)
        .optional()
        .describe(
            'How far back to look for training examples (7-730 days). Larger windows give more data but may include stale behavior. Default: 180.'
        ),
    training_population: zod
        .looseObject({})
        .optional()
        .describe('Training population filter. Use {} for all identified users.'),
    inference_population: zod
        .looseObject({})
        .optional()
        .describe('Inference population filter. Defaults to training_population if not set.'),
    cadence_days: zod
        .number()
        .min(1)
        .max(autoresearchPartialUpdateBodyCadenceDaysMax)
        .optional()
        .describe('Re-score the inference population every N days (1-365). Default: 1.'),
    iteration_budget: zod
        .number()
        .min(1)
        .max(autoresearchPartialUpdateBodyIterationBudgetMax)
        .optional()
        .describe('Total training iterations allowed for the autoresearch loop (1-500). Default: 50.'),
    success_auc: zod
        .number()
        .nullish()
        .describe('Target AUC threshold. Training stops early if reached. Default: 0.75.'),
    plateau_iterations: zod
        .number()
        .min(autoresearchPartialUpdateBodyPlateauIterationsMin)
        .max(autoresearchPartialUpdateBodyPlateauIterationsMax)
        .optional()
        .describe('Stop training if no improvement in this many consecutive iterations. Default: 10.'),
    output_person_property: zod
        .string()
        .max(autoresearchPartialUpdateBodyOutputPersonPropertyMax)
        .optional()
        .describe(
            "Person property name for the prediction score, e.g. 'predicted_p_pageview'. Auto-derived from target_event if omitted. Letters, digits, and _ $ . - only; must be unique among this project's non-archived pipelines."
        ),
})

/**
 * Start an asynchronous training run for this pipeline. Creates a Task/TaskRun sandbox where the autoresearch agent iterates on features and models, and returns the run immediately with status 'running'. Poll the training run until it reaches a terminal status (completed or failed); no champion model exists until the run completes and server-side promotion runs.
 * @summary Start a training run
 */
export const autoresearchTrainCreateBodyIterationBudgetMax = 500

export const AutoresearchTrainCreateBody = /* @__PURE__ */ zod.object({
    iteration_budget: zod
        .number()
        .min(1)
        .max(autoresearchTrainCreateBodyIterationBudgetMax)
        .optional()
        .describe('Override the pipeline iteration budget for this training run.'),
})

/**
 * Resolve a template key and optional overrides into a concrete pipeline config. For activity-based templates ('likely_active_soon', 'at_risk_of_inactivity', 'return_after_first_use'), the target event is auto-resolved from your event schema — check resolved_activity_event and activity_event_alternatives, then override if needed. For 'feature_adoption' and 'repeat_key_behavior', supply target_event. After resolving, call autoresearch-validate-create to check volume and warnings, then autoresearch-create to create the pipeline.
 * @summary Resolve a template
 */
export const autoresearchResolveTemplateCreateBodyHorizonDaysMax = 365

export const AutoresearchResolveTemplateCreateBody = /* @__PURE__ */ zod.object({
    template_key: zod
        .enum([
            'likely_active_soon',
            'at_risk_of_inactivity',
            'return_after_first_use',
            'feature_adoption',
            'repeat_key_behavior',
        ])
        .describe(
            '\* `likely_active_soon` - likely_active_soon\n\* `at_risk_of_inactivity` - at_risk_of_inactivity\n\* `return_after_first_use` - return_after_first_use\n\* `feature_adoption` - feature_adoption\n\* `repeat_key_behavior` - repeat_key_behavior'
        )
        .describe(
            'Template to resolve. Use autoresearch-templates-list to see all available templates with descriptions. Required.\n\n\* `likely_active_soon` - likely_active_soon\n\* `at_risk_of_inactivity` - at_risk_of_inactivity\n\* `return_after_first_use` - return_after_first_use\n\* `feature_adoption` - feature_adoption\n\* `repeat_key_behavior` - repeat_key_behavior'
        ),
    target_event: zod
        .string()
        .optional()
        .describe(
            "Event or action name to use as the prediction target. Required for 'feature_adoption' and 'repeat_key_behavior'. Optional override for activity-based templates ('likely_active_soon', 'at_risk_of_inactivity', 'return_after_first_use') — omit to use the auto-resolved event."
        ),
    horizon_days: zod
        .number()
        .min(1)
        .max(autoresearchResolveTemplateCreateBodyHorizonDaysMax)
        .optional()
        .describe("Override the template's default prediction horizon in days."),
})

/**
 * Validate a proposed pipeline's target event and population before creating it. Returns volume estimates, base rate, and any warnings. Warnings with severity='error' must be resolved before creation can proceed. Call this before autoresearch-create.
 * @summary Validate a pipeline definition
 */
export const autoresearchValidateCreateBodyTargetEventDefault = ``
export const autoresearchValidateCreateBodyHorizonDaysDefault = 7
export const autoresearchValidateCreateBodyHorizonDaysMax = 365

export const autoresearchValidateCreateBodyTrainingLookbackDaysDefault = 180
export const autoresearchValidateCreateBodyTrainingLookbackDaysMin = 7
export const autoresearchValidateCreateBodyTrainingLookbackDaysMax = 730

export const AutoresearchValidateCreateBody = /* @__PURE__ */ zod.object({
    target_event: zod
        .string()
        .default(autoresearchValidateCreateBodyTargetEventDefault)
        .describe(
            "Event name to predict, e.g. '$pageview'. Must exist in the team's event schema. Omit when predicting an action target (pass target_definition instead)."
        ),
    target_definition: zod
        .unknown()
        .optional()
        .describe(
            'Optional target definition. Pass {\"type\": \"action\", \"action_id\": N} to predict a PostHog action (multi-step \/ property \/ autocapture matcher) instead of a single event.'
        ),
    horizon_days: zod
        .number()
        .min(1)
        .max(autoresearchValidateCreateBodyHorizonDaysMax)
        .default(autoresearchValidateCreateBodyHorizonDaysDefault)
        .describe('Predict whether the target event occurs within this many days.'),
    training_lookback_days: zod
        .number()
        .min(autoresearchValidateCreateBodyTrainingLookbackDaysMin)
        .max(autoresearchValidateCreateBodyTrainingLookbackDaysMax)
        .default(autoresearchValidateCreateBodyTrainingLookbackDaysDefault)
        .describe('How far back to look for training examples. Default: 180.'),
    training_population: zod
        .looseObject({})
        .optional()
        .describe('Population filter for training examples. Use {} for all identified users.'),
    inference_population: zod
        .looseObject({})
        .optional()
        .describe('Population filter for daily scoring. Defaults to training_population if not provided.'),
})
