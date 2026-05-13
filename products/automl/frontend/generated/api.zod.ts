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
