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
 * Staff-only, unscoped cohort calculation tooling.
 *
 * Replaces the prod-shell runbook for stuck cohort calculations: look up any team's cohort by
 * id, list cohorts whose calculation is stuck, and force-recalculate by bumping
 * pending_version and enqueueing through the same task path organic saves use.
 *
 * Registered on the root router so it is not team-nested; staff act on cohorts in teams they
 * do not belong to. Cohort.objects is not fail-closed today (the model is on the scoping
 * baseline) — if Cohort migrates to a fail-closed manager, these cross-team queries must
 * switch to the explicit unscoped escape hatch.
 */
export const cohortsStaffRecalculateCreateBodyCohortIdsMax = 10

export const CohortsStaffRecalculateCreateBody = /* @__PURE__ */ zod.object({
    cohort_ids: zod
        .array(zod.number())
        .min(1)
        .max(cohortsStaffRecalculateCreateBodyCohortIdsMax)
        .describe('Cohort ids to force-recalculate (max 10 per request).'),
})

export const cohortsCreateBodyNameMax = 400

export const cohortsCreateBodyDescriptionMax = 1000

export const cohortsCreateBodyCreateStaticPersonIdsDefault = []
export const cohortsCreateBodyCreateStaticPersonIdsMax = 1000

export const CohortsCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(cohortsCreateBodyNameMax).nullish(),
    description: zod.string().max(cohortsCreateBodyDescriptionMax).optional(),
    groups: zod.unknown().optional(),
    deleted: zod.boolean().optional(),
    filters: zod
        .union([
            zod.object({
                properties: zod
                    .record(zod.string(), zod.unknown())
                    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)'),
                filterTestAccounts: zod.union([zod.boolean(), zod.null()]).optional(),
            }),
            zod.null(),
        ])
        .optional(),
    query: zod.unknown().optional(),
    is_static: zod.boolean().optional(),
    cohort_type: zod
        .union([
            zod
                .enum(['static', 'person_property', 'behavioral', 'realtime', 'analytical'])
                .describe(
                    '\* `static` - static\n\* `person_property` - person_property\n\* `behavioral` - behavioral\n\* `realtime` - realtime\n\* `analytical` - analytical'
                ),
            zod.enum(['']),
            zod.null(),
        ])
        .optional()
        .describe(
            'Type of cohort based on filter complexity\n\n\* `static` - static\n\* `person_property` - person_property\n\* `behavioral` - behavioral\n\* `realtime` - realtime\n\* `analytical` - analytical'
        ),
    realtime_enabled: zod
        .boolean()
        .optional()
        .describe(
            "Whether realtime is on for this cohort, so PostHog keeps its membership current for feature flags and workflows. Send true when you create a cohort to turn realtime on for it. It stays false when the project has no realtime cohorts or the cohort's criteria can't be realtime. For an existing cohort, use the `realtime` endpoint to turn it on or off."
        ),
    _create_in_folder: zod.string().optional(),
    _create_static_person_ids: zod
        .array(zod.string())
        .max(cohortsCreateBodyCreateStaticPersonIdsMax)
        .default(cohortsCreateBodyCreateStaticPersonIdsDefault)
        .describe('Person UUIDs to add to a new static cohort.'),
})

export const cohortsUpdateBodyNameMax = 400

export const cohortsUpdateBodyDescriptionMax = 1000

export const cohortsUpdateBodyCreateStaticPersonIdsDefault = []
export const cohortsUpdateBodyCreateStaticPersonIdsMax = 1000

export const CohortsUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(cohortsUpdateBodyNameMax).nullish(),
    description: zod.string().max(cohortsUpdateBodyDescriptionMax).optional(),
    groups: zod.unknown().optional(),
    deleted: zod.boolean().optional(),
    filters: zod
        .union([
            zod.object({
                properties: zod
                    .record(zod.string(), zod.unknown())
                    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)'),
                filterTestAccounts: zod.union([zod.boolean(), zod.null()]).optional(),
            }),
            zod.null(),
        ])
        .optional(),
    query: zod.unknown().optional(),
    is_static: zod.boolean().optional(),
    cohort_type: zod
        .union([
            zod
                .enum(['static', 'person_property', 'behavioral', 'realtime', 'analytical'])
                .describe(
                    '\* `static` - static\n\* `person_property` - person_property\n\* `behavioral` - behavioral\n\* `realtime` - realtime\n\* `analytical` - analytical'
                ),
            zod.enum(['']),
            zod.null(),
        ])
        .optional()
        .describe(
            'Type of cohort based on filter complexity\n\n\* `static` - static\n\* `person_property` - person_property\n\* `behavioral` - behavioral\n\* `realtime` - realtime\n\* `analytical` - analytical'
        ),
    realtime_enabled: zod
        .boolean()
        .optional()
        .describe(
            "Whether realtime is on for this cohort, so PostHog keeps its membership current for feature flags and workflows. Send true when you create a cohort to turn realtime on for it. It stays false when the project has no realtime cohorts or the cohort's criteria can't be realtime. For an existing cohort, use the `realtime` endpoint to turn it on or off."
        ),
    _create_in_folder: zod.string().optional(),
    _create_static_person_ids: zod
        .array(zod.string())
        .max(cohortsUpdateBodyCreateStaticPersonIdsMax)
        .default(cohortsUpdateBodyCreateStaticPersonIdsDefault)
        .describe('Person UUIDs to add to a new static cohort.'),
})

export const cohortsPartialUpdateBodyNameMax = 400

export const cohortsPartialUpdateBodyDescriptionMax = 1000

export const cohortsPartialUpdateBodyCreateStaticPersonIdsDefault = []
export const cohortsPartialUpdateBodyCreateStaticPersonIdsMax = 1000

export const CohortsPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(cohortsPartialUpdateBodyNameMax).nullish(),
    description: zod.string().max(cohortsPartialUpdateBodyDescriptionMax).optional(),
    groups: zod.unknown().optional(),
    deleted: zod.boolean().optional(),
    filters: zod
        .union([
            zod.object({
                properties: zod
                    .record(zod.string(), zod.unknown())
                    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)'),
                filterTestAccounts: zod.union([zod.boolean(), zod.null()]).optional(),
            }),
            zod.null(),
        ])
        .optional(),
    query: zod.unknown().optional(),
    is_static: zod.boolean().optional(),
    cohort_type: zod
        .union([
            zod
                .enum(['static', 'person_property', 'behavioral', 'realtime', 'analytical'])
                .describe(
                    '\* `static` - static\n\* `person_property` - person_property\n\* `behavioral` - behavioral\n\* `realtime` - realtime\n\* `analytical` - analytical'
                ),
            zod.enum(['']),
            zod.null(),
        ])
        .optional()
        .describe(
            'Type of cohort based on filter complexity\n\n\* `static` - static\n\* `person_property` - person_property\n\* `behavioral` - behavioral\n\* `realtime` - realtime\n\* `analytical` - analytical'
        ),
    realtime_enabled: zod
        .boolean()
        .optional()
        .describe(
            "Whether realtime is on for this cohort, so PostHog keeps its membership current for feature flags and workflows. Send true when you create a cohort to turn realtime on for it. It stays false when the project has no realtime cohorts or the cohort's criteria can't be realtime. For an existing cohort, use the `realtime` endpoint to turn it on or off."
        ),
    _create_in_folder: zod.string().optional(),
    _create_static_person_ids: zod
        .array(zod.string())
        .max(cohortsPartialUpdateBodyCreateStaticPersonIdsMax)
        .default(cohortsPartialUpdateBodyCreateStaticPersonIdsDefault)
        .describe('Person UUIDs to add to a new static cohort.'),
})

export const cohortsAddPersonsToStaticCohortPartialUpdateBodyPersonIdsMax = 1000

export const CohortsAddPersonsToStaticCohortPartialUpdateBody = /* @__PURE__ */ zod.object({
    person_ids: zod
        .array(zod.uuid())
        .max(cohortsAddPersonsToStaticCohortPartialUpdateBodyPersonIdsMax)
        .optional()
        .describe(
            'Person UUIDs to add to the cohort (the `id` column of the persons table, not distinct IDs). At most 1000 per request.'
        ),
})

/**
 * Turn realtime on or off for a cohort. Turning it on also turns it on for every realtime cohort it includes as criteria, and PostHog prepares them from past events before feature flags can target them.
 */
export const CohortsRealtimeCreateBody = /* @__PURE__ */ zod.object({
    enabled: zod
        .boolean()
        .describe(
            'True turns realtime on for the cohort and for every realtime cohort it includes as criteria, and starts preparing them from past events. False turns realtime off. PostHog refuses that while a feature flag, an active workflow, or another cohort with realtime on reads the cohort.'
        ),
})

export const CohortsRemovePersonFromStaticCohortPartialUpdateBody = /* @__PURE__ */ zod.object({
    person_id: zod.uuid().optional().describe('Person UUID to remove from the cohort'),
})
