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
 * Create a new pipeline in draft state.
 */
export const AutomlPipelinesCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string(),
        task_type: zod
            .enum(['clustering', 'classification', 'regression', 'forecasting'])
            .describe(
                '\* `clustering` - CLUSTERING\n\* `classification` - CLASSIFICATION\n\* `regression` - REGRESSION\n\* `forecasting` - FORECASTING'
            ),
        config: zod.record(zod.string(), zod.unknown()),
        training_population: zod.record(zod.string(), zod.unknown()),
        inference_population: zod.record(zod.string(), zod.unknown()),
        description: zod.string().optional(),
        autonomy: zod
            .enum(['shadow_only', 'champion_only', 'promote_eligible'])
            .optional()
            .describe(
                '\* `shadow_only` - SHADOW_ONLY\n\* `champion_only` - CHAMPION_ONLY\n\* `promote_eligible` - PROMOTE_ELIGIBLE'
            ),
        inference_cadence: zod
            .enum(['hourly', 'daily', 'weekly', 'monthly', 'never'])
            .optional()
            .describe(
                '\* `hourly` - HOURLY\n\* `daily` - DAILY\n\* `weekly` - WEEKLY\n\* `monthly` - MONTHLY\n\* `never` - NEVER'
            ),
        retraining_cadence: zod
            .enum(['hourly', 'daily', 'weekly', 'monthly', 'never'])
            .optional()
            .describe(
                '\* `hourly` - HOURLY\n\* `daily` - DAILY\n\* `weekly` - WEEKLY\n\* `monthly` - MONTHLY\n\* `never` - NEVER'
            ),
        output_property_name: zod.string().optional(),
    })
    .describe(
        "Request body for ``POST \/automl_pipelines\/``.\n\n``team_id`` and ``created_by_id`` are injected by the view from the\nrequest scope and aren't part of the DTO."
    )

/**
 * Apply partial config updates. Use start / pause / resume / archive for status transitions.
 */
export const AutomlPipelinesPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().nullish(),
        description: zod.string().nullish(),
        autonomy: zod
            .union([
                zod
                    .enum(['shadow_only', 'champion_only', 'promote_eligible'])
                    .describe(
                        '\* `shadow_only` - SHADOW_ONLY\n\* `champion_only` - CHAMPION_ONLY\n\* `promote_eligible` - PROMOTE_ELIGIBLE'
                    ),
                zod.null(),
            ])
            .optional(),
        inference_cadence: zod
            .union([
                zod
                    .enum(['hourly', 'daily', 'weekly', 'monthly', 'never'])
                    .describe(
                        '\* `hourly` - HOURLY\n\* `daily` - DAILY\n\* `weekly` - WEEKLY\n\* `monthly` - MONTHLY\n\* `never` - NEVER'
                    ),
                zod.null(),
            ])
            .optional(),
        retraining_cadence: zod
            .union([
                zod
                    .enum(['hourly', 'daily', 'weekly', 'monthly', 'never'])
                    .describe(
                        '\* `hourly` - HOURLY\n\* `daily` - DAILY\n\* `weekly` - WEEKLY\n\* `monthly` - MONTHLY\n\* `never` - NEVER'
                    ),
                zod.null(),
            ])
            .optional(),
        output_property_name: zod.string().nullish(),
        config: zod.record(zod.string(), zod.unknown()).nullish(),
        training_population: zod.record(zod.string(), zod.unknown()).nullish(),
        inference_population: zod.record(zod.string(), zod.unknown()).nullish(),
        extra: zod.record(zod.string(), zod.unknown()).optional(),
    })
    .describe(
        'Request body for ``PATCH \/automl_pipelines\/{id}\/``.\n\nAll fields are optional; ``None`` means leave unchanged. Status\ntransitions go through the dedicated start \/ pause \/ resume \/ archive\nactions instead of this endpoint.'
    )

/**
 * Persist a completed training run as a new model version.

Always recorded as ``challenger`` by default — promotion to champion is
the explicit ``promote`` action below. Called by the bootstrap and
retraining agents from inside their sandbox after the trainer returns.
 */
export const AutomlPipelinesModelVersionsCreateBody = /* @__PURE__ */ zod
    .object({
        metrics: zod.record(zod.string(), zod.unknown()),
        leaderboard: zod.array(zod.record(zod.string(), zod.unknown())),
        role: zod
            .enum(['champion', 'challenger', 'archived'])
            .optional()
            .describe('\* `champion` - CHAMPION\n\* `challenger` - CHALLENGER\n\* `archived` - ARCHIVED'),
        training_params: zod.record(zod.string(), zod.unknown()).optional(),
        tracking_metadata: zod.record(zod.string(), zod.unknown()).optional(),
        eval_metric: zod.string().optional(),
        problem_type: zod.string().optional(),
        artifact_uri: zod.string().optional(),
        features_hash: zod.string().optional(),
        rows_train: zod.number().nullish(),
        rows_val: zod.number().nullish(),
        rows_test: zod.number().nullish(),
        training_task_id: zod.uuid().nullish(),
    })
    .describe(
        'Request body for ``POST \/automl_pipelines\/{id}\/model_versions\/``.\n\nCalled by the bootstrap \/ retraining agent when a training run finishes.\n``role`` defaults to ``challenger`` so a fresh run never auto-displaces the\nexisting champion — promotion is a separate explicit step.'
    )

/**
 * Flip a run to a terminal state and write the agent's final outcome report.

Single-shot — once a run reaches a terminal state, re-calling this no-ops
(returns the already-terminal DTO). Lets the agent retry the MCP call
after a transient network blip without overwriting the timeline.
Rejects ``status='running'`` with 400 (terminal status required).
 */
export const AutomlPipelinesRunsRecordBootstrapOutcomeCreateBody = /* @__PURE__ */ zod
    .object({
        status: zod
            .enum(['running', 'succeeded', 'failed', 'aborted'])
            .describe(
                '\* `running` - RUNNING\n\* `succeeded` - SUCCEEDED\n\* `failed` - FAILED\n\* `aborted` - ABORTED'
            ),
        outcome_report: zod.string(),
        failure_reason: zod.string().optional(),
        cli_run_id: zod.string().optional(),
        agent_session_id: zod.string().optional(),
    })
    .describe(
        'Request body for ``POST \/automl_pipelines\/{id}\/runs\/{run_id}\/record_bootstrap_outcome\/``.\n\nCalled by the bootstrap agent as the final checkpoint of a run. Flips the\nrun to a terminal status and writes the structured markdown outcome report\nsurfaced on the pipeline-detail page.'
    )

/**
 * Stash the agent's EDA output on an in-progress run.

Called by the bootstrap agent between ``automl eda`` and ``automl train``.
Status stays at ``running`` — EDA is a mid-run checkpoint, not terminal.
Idempotent in the sense that a second call overwrites the prior payload
(the CLI's ``eda.yaml`` is regenerated on every re-run).
 */
export const AutomlPipelinesRunsRecordEdaResultCreateBody = /* @__PURE__ */ zod
    .object({
        eda_result: zod.record(zod.string(), zod.unknown()),
        cli_run_id: zod.string().optional(),
    })
    .describe(
        "Request body for ``POST \/automl_pipelines\/{id}\/runs\/{run_id}\/record_eda_result\/``.\n\nCalled by the bootstrap agent between ``automl eda`` and ``automl train``.\nThe ``eda_result`` payload is schemaless on purpose so the CLI's\n``eda.yaml`` shape can evolve without forcing a migration."
    )

/**
 * Run preflight validation against a proposed pipeline config.

Side-effect-free: nothing is written, no pipeline is created. Same body
shape as the create endpoint; call this first so the user can see the
validation report (volume, base rate, leakage warnings, sample plan)
before committing to a pipeline.
 */
export const AutomlPipelinesValidateCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string(),
        task_type: zod
            .enum(['clustering', 'classification', 'regression', 'forecasting'])
            .describe(
                '\* `clustering` - CLUSTERING\n\* `classification` - CLASSIFICATION\n\* `regression` - REGRESSION\n\* `forecasting` - FORECASTING'
            ),
        config: zod.record(zod.string(), zod.unknown()),
        training_population: zod.record(zod.string(), zod.unknown()),
        inference_population: zod.record(zod.string(), zod.unknown()),
        description: zod.string().optional(),
        autonomy: zod
            .enum(['shadow_only', 'champion_only', 'promote_eligible'])
            .optional()
            .describe(
                '\* `shadow_only` - SHADOW_ONLY\n\* `champion_only` - CHAMPION_ONLY\n\* `promote_eligible` - PROMOTE_ELIGIBLE'
            ),
        inference_cadence: zod
            .enum(['hourly', 'daily', 'weekly', 'monthly', 'never'])
            .optional()
            .describe(
                '\* `hourly` - HOURLY\n\* `daily` - DAILY\n\* `weekly` - WEEKLY\n\* `monthly` - MONTHLY\n\* `never` - NEVER'
            ),
        retraining_cadence: zod
            .enum(['hourly', 'daily', 'weekly', 'monthly', 'never'])
            .optional()
            .describe(
                '\* `hourly` - HOURLY\n\* `daily` - DAILY\n\* `weekly` - WEEKLY\n\* `monthly` - MONTHLY\n\* `never` - NEVER'
            ),
        output_property_name: zod.string().optional(),
    })
    .describe(
        "Request body for ``POST \/automl_pipelines\/``.\n\n``team_id`` and ``created_by_id`` are injected by the view from the\nrequest scope and aren't part of the DTO."
    )
