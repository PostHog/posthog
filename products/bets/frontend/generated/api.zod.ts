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

export const betsCreateBodyTitleMax = 160

export const betsCreateBodyStatementMax = 10000

export const betsCreateBodyAudienceDefault = ``
export const betsCreateBodyAudienceMax = 500

export const betsCreateBodyAreaDefault = ``
export const betsCreateBodyAreaMax = 120

export const betsCreateBodyRepositoryMax = 255

export const betsCreateBodyRepositoryRegExp = new RegExp('^[\\w.-]+\/[\\w.-]+$')
export const betsCreateBodyRepositoriesItemMax = 255

export const betsCreateBodyRepositoriesItemRegExp = new RegExp('^[\\w.-]+\/[\\w.-]+$')
export const betsCreateBodyRepositoriesMax = 10

export const betsCreateBodyGoalInsightMax = 32

export const betsCreateBodyGoalDescriptionMax = 2000

export const betsCreateBodyGoalMetricMax = 255

export const betsCreateBodyIdeasItemMax = 255

export const betsCreateBodyIdeasMax = 5

export const betsCreateBodySecondaryMetricsItemInsightMax = 32

export const betsCreateBodySecondaryMetricsItemNameMax = 255

export const betsCreateBodySecondaryMetricsItemDirectionDefault = `increase`
export const betsCreateBodySecondaryMetricsItemMaxRegressionDefault = 0.05
export const betsCreateBodySecondaryMetricsItemMaxRegressionMin = 0
export const betsCreateBodySecondaryMetricsItemMaxRegressionMax = 1

export const betsCreateBodyTargetRegExp = new RegExp('^-?\\d{0,16}(?:\\.\\d{0,4})?$')
export const betsCreateBodyDirectionDefault = `increase`
export const betsCreateBodyUnitDefault = ``
export const betsCreateBodyUnitMax = 32

export const betsCreateBodyBudgetCentsMin = 0
export const betsCreateBodyBudgetCentsMax = 1000000000

export const BetsCreateBody = /* @__PURE__ */ zod.object({
    operation_id: zod.uuid().optional().describe('Stable ID for retrying creation without duplicates.'),
    title: zod.string().max(betsCreateBodyTitleMax).describe('Short name of the bet.'),
    statement: zod.string().max(betsCreateBodyStatementMax).describe('What you believe will improve and why.'),
    audience: zod
        .string()
        .max(betsCreateBodyAudienceMax)
        .default(betsCreateBodyAudienceDefault)
        .describe('People this bet aims to help.'),
    area: zod
        .string()
        .max(betsCreateBodyAreaMax)
        .default(betsCreateBodyAreaDefault)
        .describe('Product area for filtering.'),
    repository: zod
        .string()
        .max(betsCreateBodyRepositoryMax)
        .regex(betsCreateBodyRepositoryRegExp)
        .optional()
        .describe('Main GitHub repository in owner\/repository form. Defaults to the first of repositories.'),
    repositories: zod
        .array(zod.string().max(betsCreateBodyRepositoriesItemMax).regex(betsCreateBodyRepositoriesItemRegExp))
        .max(betsCreateBodyRepositoriesMax)
        .optional()
        .describe('GitHub repositories Bets reads and changes, in owner\/repository form. The first is the main one.'),
    goal_insight: zod
        .string()
        .max(betsCreateBodyGoalInsightMax)
        .optional()
        .describe('Saved insight with one series that measures the goal. Leave empty and describe the goal instead.'),
    goal_description: zod
        .string()
        .max(betsCreateBodyGoalDescriptionMax)
        .optional()
        .describe('How to measure the goal, in words, when no saved insight fits. Bets finds or creates the insight.'),
    goal_metric: zod.string().max(betsCreateBodyGoalMetricMax).describe('Name of the primary metric.'),
    ideas: zod
        .array(zod.string().max(betsCreateBodyIdeasItemMax))
        .max(betsCreateBodyIdeasMax)
        .optional()
        .describe("The owner's own ideas. The Scout checks each one against the data before anyone chooses."),
    secondary_metrics: zod
        .array(
            zod.object({
                insight: zod
                    .string()
                    .max(betsCreateBodySecondaryMetricsItemInsightMax)
                    .describe('Saved PostHog insight used as a guardrail.'),
                name: zod
                    .string()
                    .max(betsCreateBodySecondaryMetricsItemNameMax)
                    .describe('Name of the guardrail metric.'),
                direction: zod
                    .enum(['increase', 'decrease'])
                    .describe('\* `increase` - Increase\n\* `decrease` - Decrease')
                    .default(betsCreateBodySecondaryMetricsItemDirectionDefault)
                    .describe(
                        'Whether higher or lower is better.\n\n\* `increase` - Increase\n\* `decrease` - Decrease'
                    ),
                max_regression: zod
                    .number()
                    .min(betsCreateBodySecondaryMetricsItemMaxRegressionMin)
                    .max(betsCreateBodySecondaryMetricsItemMaxRegressionMax)
                    .default(betsCreateBodySecondaryMetricsItemMaxRegressionDefault)
                    .describe('Largest tolerated relative regression, 0.05 for 5%.'),
            })
        )
        .optional()
        .describe('Guardrails that must not get worse.'),
    target: zod
        .stringFormat('decimal', betsCreateBodyTargetRegExp)
        .nullish()
        .describe('Target value of the primary metric. Set it after Bets finds the insight for a described goal.'),
    direction: zod
        .enum(['increase', 'decrease'])
        .describe('\* `increase` - Increase\n\* `decrease` - Decrease')
        .default(betsCreateBodyDirectionDefault)
        .describe('Whether higher or lower is better.\n\n\* `increase` - Increase\n\* `decrease` - Decrease'),
    unit: zod
        .string()
        .max(betsCreateBodyUnitMax)
        .default(betsCreateBodyUnitDefault)
        .describe('Display unit, for example %.'),
    budget_cents: zod
        .number()
        .min(betsCreateBodyBudgetCentsMin)
        .max(betsCreateBodyBudgetCentsMax)
        .describe('Budget for this bet in USD cents.'),
})

export const betsPartialUpdateBodyTitleMax = 160

export const betsPartialUpdateBodyStatementMax = 10000

export const betsPartialUpdateBodyAudienceDefault = ``
export const betsPartialUpdateBodyAudienceMax = 500

export const betsPartialUpdateBodyAreaDefault = ``
export const betsPartialUpdateBodyAreaMax = 120

export const betsPartialUpdateBodyRepositoryMax = 255

export const betsPartialUpdateBodyRepositoryRegExp = new RegExp('^[\\w.-]+\/[\\w.-]+$')
export const betsPartialUpdateBodyRepositoriesItemMax = 255

export const betsPartialUpdateBodyRepositoriesItemRegExp = new RegExp('^[\\w.-]+\/[\\w.-]+$')
export const betsPartialUpdateBodyRepositoriesMax = 10

export const betsPartialUpdateBodyGoalInsightMax = 32

export const betsPartialUpdateBodyGoalDescriptionMax = 2000

export const betsPartialUpdateBodyGoalMetricMax = 255

export const betsPartialUpdateBodyIdeasItemMax = 255

export const betsPartialUpdateBodyIdeasMax = 5

export const betsPartialUpdateBodySecondaryMetricsItemInsightMax = 32

export const betsPartialUpdateBodySecondaryMetricsItemNameMax = 255

export const betsPartialUpdateBodySecondaryMetricsItemDirectionDefault = `increase`
export const betsPartialUpdateBodySecondaryMetricsItemMaxRegressionDefault = 0.05
export const betsPartialUpdateBodySecondaryMetricsItemMaxRegressionMin = 0
export const betsPartialUpdateBodySecondaryMetricsItemMaxRegressionMax = 1

export const betsPartialUpdateBodyTargetRegExp = new RegExp('^-?\\d{0,16}(?:\\.\\d{0,4})?$')
export const betsPartialUpdateBodyDirectionDefault = `increase`
export const betsPartialUpdateBodyUnitDefault = ``
export const betsPartialUpdateBodyUnitMax = 32

export const betsPartialUpdateBodyBudgetCentsMin = 0
export const betsPartialUpdateBodyBudgetCentsMax = 1000000000

export const BetsPartialUpdateBody = /* @__PURE__ */ zod.object({
    operation_id: zod.uuid().optional().describe('Stable ID for retrying creation without duplicates.'),
    title: zod.string().max(betsPartialUpdateBodyTitleMax).optional().describe('Short name of the bet.'),
    statement: zod
        .string()
        .max(betsPartialUpdateBodyStatementMax)
        .optional()
        .describe('What you believe will improve and why.'),
    audience: zod
        .string()
        .max(betsPartialUpdateBodyAudienceMax)
        .default(betsPartialUpdateBodyAudienceDefault)
        .describe('People this bet aims to help.'),
    area: zod
        .string()
        .max(betsPartialUpdateBodyAreaMax)
        .default(betsPartialUpdateBodyAreaDefault)
        .describe('Product area for filtering.'),
    repository: zod
        .string()
        .max(betsPartialUpdateBodyRepositoryMax)
        .regex(betsPartialUpdateBodyRepositoryRegExp)
        .optional()
        .describe('Main GitHub repository in owner\/repository form. Defaults to the first of repositories.'),
    repositories: zod
        .array(
            zod
                .string()
                .max(betsPartialUpdateBodyRepositoriesItemMax)
                .regex(betsPartialUpdateBodyRepositoriesItemRegExp)
        )
        .max(betsPartialUpdateBodyRepositoriesMax)
        .optional()
        .describe('GitHub repositories Bets reads and changes, in owner\/repository form. The first is the main one.'),
    goal_insight: zod
        .string()
        .max(betsPartialUpdateBodyGoalInsightMax)
        .optional()
        .describe('Saved insight with one series that measures the goal. Leave empty and describe the goal instead.'),
    goal_description: zod
        .string()
        .max(betsPartialUpdateBodyGoalDescriptionMax)
        .optional()
        .describe('How to measure the goal, in words, when no saved insight fits. Bets finds or creates the insight.'),
    goal_metric: zod
        .string()
        .max(betsPartialUpdateBodyGoalMetricMax)
        .optional()
        .describe('Name of the primary metric.'),
    ideas: zod
        .array(zod.string().max(betsPartialUpdateBodyIdeasItemMax))
        .max(betsPartialUpdateBodyIdeasMax)
        .optional()
        .describe("The owner's own ideas. The Scout checks each one against the data before anyone chooses."),
    secondary_metrics: zod
        .array(
            zod.object({
                insight: zod
                    .string()
                    .max(betsPartialUpdateBodySecondaryMetricsItemInsightMax)
                    .describe('Saved PostHog insight used as a guardrail.'),
                name: zod
                    .string()
                    .max(betsPartialUpdateBodySecondaryMetricsItemNameMax)
                    .describe('Name of the guardrail metric.'),
                direction: zod
                    .enum(['increase', 'decrease'])
                    .describe('\* `increase` - Increase\n\* `decrease` - Decrease')
                    .default(betsPartialUpdateBodySecondaryMetricsItemDirectionDefault)
                    .describe(
                        'Whether higher or lower is better.\n\n\* `increase` - Increase\n\* `decrease` - Decrease'
                    ),
                max_regression: zod
                    .number()
                    .min(betsPartialUpdateBodySecondaryMetricsItemMaxRegressionMin)
                    .max(betsPartialUpdateBodySecondaryMetricsItemMaxRegressionMax)
                    .default(betsPartialUpdateBodySecondaryMetricsItemMaxRegressionDefault)
                    .describe('Largest tolerated relative regression, 0.05 for 5%.'),
            })
        )
        .optional()
        .describe('Guardrails that must not get worse.'),
    target: zod
        .stringFormat('decimal', betsPartialUpdateBodyTargetRegExp)
        .nullish()
        .describe('Target value of the primary metric. Set it after Bets finds the insight for a described goal.'),
    direction: zod
        .enum(['increase', 'decrease'])
        .describe('\* `increase` - Increase\n\* `decrease` - Decrease')
        .default(betsPartialUpdateBodyDirectionDefault)
        .describe('Whether higher or lower is better.\n\n\* `increase` - Increase\n\* `decrease` - Decrease'),
    unit: zod
        .string()
        .max(betsPartialUpdateBodyUnitMax)
        .default(betsPartialUpdateBodyUnitDefault)
        .describe('Display unit, for example %.'),
    budget_cents: zod
        .number()
        .min(betsPartialUpdateBodyBudgetCentsMin)
        .max(betsPartialUpdateBodyBudgetCentsMax)
        .optional()
        .describe('Budget for this bet in USD cents.'),
})

export const betsIdeasCreateBodyTitleMax = 255

export const BetsIdeasCreateBody = /* @__PURE__ */ zod.object({
    title: zod.string().max(betsIdeasCreateBodyTitleMax).describe("The owner's idea, in one sentence."),
})

export const BetsStatusCreateBody = /* @__PURE__ */ zod.object({
    status: zod
        .enum(['running', 'paused', 'closed'])
        .describe('\* `running` - Start or resume\n\* `paused` - Pause\n\* `closed` - Close')
        .describe(
            'Resume, pause or close the bet.\n\n\* `running` - Start or resume\n\* `paused` - Pause\n\* `closed` - Close'
        ),
})

export const betsWorkCreateBodyReasonDefault = ``
export const betsWorkCreateBodyReasonMax = 1000

export const betsWorkCreateBodyPlanOneDaysMin = 2
export const betsWorkCreateBodyPlanOneDaysMax = 365

export const betsWorkCreateBodyPlanOneMdeMin = 0.1
export const betsWorkCreateBodyPlanOneMdeMax = 100

export const BetsWorkCreateBody = /* @__PURE__ */ zod.object({
    work_id: zod.uuid().describe('Work item belonging to this bet.'),
    action: zod
        .enum(['retry', 'drop', 'build', 'dismiss', 'extend'])
        .describe(
            '\* `retry` - Retry\n\* `drop` - Drop\n\* `build` - Build\n\* `dismiss` - Dismiss\n\* `extend` - Extend'
        )
        .describe(
            'Build a proposed idea, dismiss it, retry stuck work, drop an idea in progress, or extend its experiment.\n\n\* `retry` - Retry\n\* `drop` - Drop\n\* `build` - Build\n\* `dismiss` - Dismiss\n\* `extend` - Extend'
        ),
    reason: zod
        .string()
        .max(betsWorkCreateBodyReasonMax)
        .default(betsWorkCreateBodyReasonDefault)
        .describe('Why the idea is dismissed.'),
    plan: zod
        .object({
            days: zod
                .number()
                .min(betsWorkCreateBodyPlanOneDaysMin)
                .max(betsWorkCreateBodyPlanOneDaysMax)
                .describe('Days the experiment runs.'),
            mde: zod
                .number()
                .min(betsWorkCreateBodyPlanOneMdeMin)
                .max(betsWorkCreateBodyPlanOneMdeMax)
                .describe('Smallest change worth finding, in percent.'),
            audience: zod.number().min(1).describe('People a day who see the change.'),
        })
        .optional()
        .describe('The experiment plan the owner approves with a build.'),
})

export const betsSettingsPartialUpdateBodyBudgetCentsMin = 0
export const betsSettingsPartialUpdateBodyBudgetCentsMax = 1000000000

export const betsSettingsPartialUpdateBodyNorthStarInsightMax = 32

export const betsSettingsPartialUpdateBodyMinRunHoursMin = 0
export const betsSettingsPartialUpdateBodyMinRunHoursMax = 1440

export const betsSettingsPartialUpdateBodyMdePercentMin = 0.1
export const betsSettingsPartialUpdateBodyMdePercentMax = 100

export const betsSettingsPartialUpdateBodyGoalConfirmHoursMin = 0
export const betsSettingsPartialUpdateBodyGoalConfirmHoursMax = 1440

export const betsSettingsPartialUpdateBodyStepModelsOneScoutOneModelMax = 200

export const betsSettingsPartialUpdateBodyStepModelsOneScoutOneReasoningEffortDefault = ``
export const betsSettingsPartialUpdateBodyStepModelsOneScoutOneReasoningEffortMax = 20

export const betsSettingsPartialUpdateBodyStepModelsOneTrackingOneModelMax = 200

export const betsSettingsPartialUpdateBodyStepModelsOneTrackingOneReasoningEffortDefault = ``
export const betsSettingsPartialUpdateBodyStepModelsOneTrackingOneReasoningEffortMax = 20

export const betsSettingsPartialUpdateBodyStepModelsOneIdeaOneModelMax = 200

export const betsSettingsPartialUpdateBodyStepModelsOneIdeaOneReasoningEffortDefault = ``
export const betsSettingsPartialUpdateBodyStepModelsOneIdeaOneReasoningEffortMax = 20

export const BetsSettingsPartialUpdateBody = /* @__PURE__ */ zod.object({
    budget_cents: zod
        .number()
        .min(betsSettingsPartialUpdateBodyBudgetCentsMin)
        .max(betsSettingsPartialUpdateBodyBudgetCentsMax)
        .optional()
        .describe('Project budget in USD cents.'),
    north_star_insight: zod
        .string()
        .max(betsSettingsPartialUpdateBodyNorthStarInsightMax)
        .optional()
        .describe('Saved insight for the project North Star.'),
    min_run_hours: zod
        .number()
        .min(betsSettingsPartialUpdateBodyMinRunHoursMin)
        .max(betsSettingsPartialUpdateBodyMinRunHoursMax)
        .optional()
        .describe('Shortest experiment run in hours. Zero lets the plan decide.'),
    mde_percent: zod
        .number()
        .min(betsSettingsPartialUpdateBodyMdePercentMin)
        .max(betsSettingsPartialUpdateBodyMdePercentMax)
        .optional()
        .describe('Smallest relative change, in percent, an experiment plans to find.'),
    goal_confirm_hours: zod
        .number()
        .min(betsSettingsPartialUpdateBodyGoalConfirmHoursMin)
        .max(betsSettingsPartialUpdateBodyGoalConfirmHoursMax)
        .optional()
        .describe('Hours the goal metric must stay at the target before the bet counts as reached.'),
    step_models: zod
        .object({
            scout: zod
                .object({
                    model: zod
                        .string()
                        .max(betsSettingsPartialUpdateBodyStepModelsOneScoutOneModelMax)
                        .describe('Model ID, or empty for the project default.'),
                    reasoning_effort: zod
                        .string()
                        .max(betsSettingsPartialUpdateBodyStepModelsOneScoutOneReasoningEffortMax)
                        .default(betsSettingsPartialUpdateBodyStepModelsOneScoutOneReasoningEffortDefault)
                        .describe('Reasoning effort.'),
                    billing: zod
                        .enum(['credits', 'subscription'])
                        .describe('\* `credits` - PostHog credits\n\* `subscription` - ChatGPT plan')
                        .describe(
                            "Who pays for this step's model use.\n\n\* `credits` - PostHog credits\n\* `subscription` - ChatGPT plan"
                        ),
                })
                .optional()
                .describe('Model for the Scout.'),
            tracking: zod
                .object({
                    model: zod
                        .string()
                        .max(betsSettingsPartialUpdateBodyStepModelsOneTrackingOneModelMax)
                        .describe('Model ID, or empty for the project default.'),
                    reasoning_effort: zod
                        .string()
                        .max(betsSettingsPartialUpdateBodyStepModelsOneTrackingOneReasoningEffortMax)
                        .default(betsSettingsPartialUpdateBodyStepModelsOneTrackingOneReasoningEffortDefault)
                        .describe('Reasoning effort.'),
                    billing: zod
                        .enum(['credits', 'subscription'])
                        .describe('\* `credits` - PostHog credits\n\* `subscription` - ChatGPT plan')
                        .describe(
                            "Who pays for this step's model use.\n\n\* `credits` - PostHog credits\n\* `subscription` - ChatGPT plan"
                        ),
                })
                .optional()
                .describe('Model for tracking checks.'),
            idea: zod
                .object({
                    model: zod
                        .string()
                        .max(betsSettingsPartialUpdateBodyStepModelsOneIdeaOneModelMax)
                        .describe('Model ID, or empty for the project default.'),
                    reasoning_effort: zod
                        .string()
                        .max(betsSettingsPartialUpdateBodyStepModelsOneIdeaOneReasoningEffortMax)
                        .default(betsSettingsPartialUpdateBodyStepModelsOneIdeaOneReasoningEffortDefault)
                        .describe('Reasoning effort.'),
                    billing: zod
                        .enum(['credits', 'subscription'])
                        .describe('\* `credits` - PostHog credits\n\* `subscription` - ChatGPT plan')
                        .describe(
                            "Who pays for this step's model use.\n\n\* `credits` - PostHog credits\n\* `subscription` - ChatGPT plan"
                        ),
                })
                .optional()
                .describe('Model for building ideas.'),
        })
        .optional()
        .describe('Model and billing per step.'),
})
