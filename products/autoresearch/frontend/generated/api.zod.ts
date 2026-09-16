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

export const autoresearchCreateBodySuccessAucMin = 0
export const autoresearchCreateBodySuccessAucMax = 1

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
        .union([
            zod
                .object({
                    type: zod.enum(['event']),
                })
                .describe('Predict target_event. The default when target_definition is omitted.'),
            zod
                .object({
                    type: zod.enum(['action']),
                    action_id: zod.number().min(1).describe('ID of the action to predict.'),
                })
                .describe('Predict a PostHog action in this project.'),
        ])
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
        .min(autoresearchCreateBodySuccessAucMin)
        .max(autoresearchCreateBodySuccessAucMax)
        .nullish()
        .describe('Target AUC threshold (0-1). Training stops early if reached. Default: 0.75.'),
    plateau_iterations: zod
        .number()
        .min(1)
        .max(autoresearchCreateBodyPlateauIterationsMax)
        .optional()
        .describe('Stop training if no improvement in this many consecutive iterations (at least 1). Default: 10.'),
    output_person_property: zod
        .string()
        .max(autoresearchCreateBodyOutputPersonPropertyMax)
        .optional()
        .describe(
            "Person property name for the prediction score, e.g. 'predicted_p_pageview'. Auto-derived from target_event if omitted. Letters, digits, and _ $ . - only, and it cannot start with $ (reserved for PostHog's own properties); must be unique among this project's non-archived pipelines."
        ),
})

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
 * Finalize a training run. The backend selects the kept iteration with the highest holdout score, decides champion vs challenger via the promotion ladder, and persists the model. best_iteration_id is advisory: it breaks a tie at the top score and is otherwise logged and ignored. Agents cannot set the champion directly, because promotion is server-side.
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
                'Advisory nomination. The server promotes the kept iteration with the highest holdout_score; this id only breaks a tie at that score, and a lower-scoring nomination is logged and ignored.'
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
 * Record one iteration of an open training run. Idempotent on iteration_number: re-sending the same number updates that iteration. A new iteration_number is refused once the run's iteration_budget is used. The recipe is validated server-side: feature_sql must be a read-only SELECT from {anchors} keyed on person_id, and model_class must be set. The class allowlist applies only at completion, to a run that uploaded no bundle.
 * @summary Record a training iteration
 */
export const autoresearchTrainingRunsIterationsCreateBodyIterationNumberMin = 0
export const autoresearchTrainingRunsIterationsCreateBodyIterationNumberMax = 2147483647

export const autoresearchTrainingRunsIterationsCreateBodyTrainScoreMin = 0
export const autoresearchTrainingRunsIterationsCreateBodyTrainScoreMax = 1

export const autoresearchTrainingRunsIterationsCreateBodyHoldoutScoreMin = 0
export const autoresearchTrainingRunsIterationsCreateBodyHoldoutScoreMax = 1

export const autoresearchTrainingRunsIterationsCreateBodyAgentDescriptionDefault = ``
export const autoresearchTrainingRunsIterationsCreateBodyAgentDescriptionMax = 2000

export const autoresearchTrainingRunsIterationsCreateBodyAgentConfidenceMin = 0
export const autoresearchTrainingRunsIterationsCreateBodyAgentConfidenceMax = 1

export const AutoresearchTrainingRunsIterationsCreateBody = /* @__PURE__ */ zod
    .object({
        iteration_number: zod
            .number()
            .min(autoresearchTrainingRunsIterationsCreateBodyIterationNumberMin)
            .max(autoresearchTrainingRunsIterationsCreateBodyIterationNumberMax)
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
            .max(autoresearchTrainingRunsIterationsCreateBodyAgentDescriptionMax)
            .default(autoresearchTrainingRunsIterationsCreateBodyAgentDescriptionDefault)
            .describe("Agent's plain-English rationale for this iteration. Max 2000 characters."),
        agent_confidence: zod
            .number()
            .min(autoresearchTrainingRunsIterationsCreateBodyAgentConfidenceMin)
            .max(autoresearchTrainingRunsIterationsCreateBodyAgentConfidenceMax)
            .nullish()
            .describe("Agent's self-assessed confidence (0-1) that this iteration helps."),
        parent_suggestion: zod
            .uuid()
            .nullish()
            .describe(
                "UUID of the steering suggestion this iteration was spawned from, if any. Set it whenever the iteration acts on a pending suggestion — it links the iteration back to the suggestion for attribution and advances the suggestion to 'acted_on'."
            ),
    })
    .describe('Input for recording one training iteration. Validated against the recipe allowlist.')

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

export const autoresearchUpdateBodySuccessAucMin = 0
export const autoresearchUpdateBodySuccessAucMax = 1

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
        .union([
            zod
                .object({
                    type: zod.enum(['event']),
                })
                .describe('Predict target_event. The default when target_definition is omitted.'),
            zod
                .object({
                    type: zod.enum(['action']),
                    action_id: zod.number().min(1).describe('ID of the action to predict.'),
                })
                .describe('Predict a PostHog action in this project.'),
        ])
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
        .min(autoresearchUpdateBodySuccessAucMin)
        .max(autoresearchUpdateBodySuccessAucMax)
        .nullish()
        .describe('Target AUC threshold (0-1). Training stops early if reached. Default: 0.75.'),
    plateau_iterations: zod
        .number()
        .min(1)
        .max(autoresearchUpdateBodyPlateauIterationsMax)
        .optional()
        .describe('Stop training if no improvement in this many consecutive iterations (at least 1). Default: 10.'),
    output_person_property: zod
        .string()
        .max(autoresearchUpdateBodyOutputPersonPropertyMax)
        .optional()
        .describe(
            "Person property name for the prediction score, e.g. 'predicted_p_pageview'. Auto-derived from target_event if omitted. Letters, digits, and _ $ . - only, and it cannot start with $ (reserved for PostHog's own properties); must be unique among this project's non-archived pipelines."
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

export const autoresearchPartialUpdateBodySuccessAucMin = 0
export const autoresearchPartialUpdateBodySuccessAucMax = 1

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
        .union([
            zod
                .object({
                    type: zod.enum(['event']),
                })
                .describe('Predict target_event. The default when target_definition is omitted.'),
            zod
                .object({
                    type: zod.enum(['action']),
                    action_id: zod.number().min(1).describe('ID of the action to predict.'),
                })
                .describe('Predict a PostHog action in this project.'),
        ])
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
        .min(autoresearchPartialUpdateBodySuccessAucMin)
        .max(autoresearchPartialUpdateBodySuccessAucMax)
        .nullish()
        .describe('Target AUC threshold (0-1). Training stops early if reached. Default: 0.75.'),
    plateau_iterations: zod
        .number()
        .min(1)
        .max(autoresearchPartialUpdateBodyPlateauIterationsMax)
        .optional()
        .describe('Stop training if no improvement in this many consecutive iterations (at least 1). Default: 10.'),
    output_person_property: zod
        .string()
        .max(autoresearchPartialUpdateBodyOutputPersonPropertyMax)
        .optional()
        .describe(
            "Person property name for the prediction score, e.g. 'predicted_p_pageview'. Auto-derived from target_event if omitted. Letters, digits, and _ $ . - only, and it cannot start with $ (reserved for PostHog's own properties); must be unique among this project's non-archived pipelines."
        ),
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
            '\* `likely_active_soon` - Likely Active Soon\n\* `at_risk_of_inactivity` - At Risk Of Inactivity\n\* `return_after_first_use` - Return After First Use\n\* `feature_adoption` - Feature Adoption\n\* `repeat_key_behavior` - Repeat Key Behavior'
        )
        .describe(
            'Template to resolve. Use autoresearch-templates-list to see all available templates with descriptions. Required.\n\n\* `likely_active_soon` - Likely Active Soon\n\* `at_risk_of_inactivity` - At Risk Of Inactivity\n\* `return_after_first_use` - Return After First Use\n\* `feature_adoption` - Feature Adoption\n\* `repeat_key_behavior` - Repeat Key Behavior'
        ),
    target_event: zod
        .string()
        .optional()
        .describe(
            "Event name to use as the prediction target. Required for 'feature_adoption' and 'repeat_key_behavior'. Optional override for activity-based templates ('likely_active_soon', 'at_risk_of_inactivity', 'return_after_first_use'); omit to use the auto-resolved event. To predict an action, create the pipeline with target_definition after resolving."
        ),
    horizon_days: zod
        .number()
        .min(1)
        .max(autoresearchResolveTemplateCreateBodyHorizonDaysMax)
        .optional()
        .describe("Override the template's default prediction horizon in days."),
})

/**
 * Validate a proposed pipeline's target event and population before creating it. Returns volume estimates, base rate, and any warnings. Creation does not enforce the result: 'population_too_large' and 'horizon_exceeds_lookback' mean a training run would fail, and the other 'error' codes mean the data is too thin for a reliable model. Call this before autoresearch-create.
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
        .union([
            zod
                .object({
                    type: zod.enum(['event']),
                })
                .describe('Predict target_event. The default when target_definition is omitted.'),
            zod
                .object({
                    type: zod.enum(['action']),
                    action_id: zod.number().min(1).describe('ID of the action to predict.'),
                })
                .describe('Predict a PostHog action in this project.'),
        ])
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
        .describe(
            'Population filter for daily scoring. When omitted or empty, the training population is counted, as creation stores it.'
        ),
})
