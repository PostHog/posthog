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
 * List, retrieve, open, record iterations into, and complete training runs for a pipeline.
 *
 * The write endpoints let an external (bring-your-own) agent or a scheduled job drive a
 * training run directly — recording each iteration as it completes rather than via a single
 * terminal sandbox output. Recipe validation and champion promotion stay server-side.
 */
export const autoresearchTrainingRunsCreateBodyIterationBudgetMin = -2147483648
export const autoresearchTrainingRunsCreateBodyIterationBudgetMax = 2147483647

export const AutoresearchTrainingRunsCreateBody = /* @__PURE__ */ zod.object({
    pipeline: zod.uuid().describe('Pipeline this training run belongs to.'),
    task_id: zod.uuid().nullish().describe('Parent Task ID in the tasks sandbox. Null for stub runs.'),
    task_run_id: zod.uuid().nullish().describe('Task sandbox run ID. Null for stub\/synchronous training runs.'),
    iteration_budget: zod
        .number()
        .min(autoresearchTrainingRunsCreateBodyIterationBudgetMin)
        .max(autoresearchTrainingRunsCreateBodyIterationBudgetMax)
        .optional()
        .describe('Maximum iterations allowed for this run.'),
})

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
