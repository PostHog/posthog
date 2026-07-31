/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import {
    CohortApi,
    PatchedAddPersonsToStaticCohortRequestApi,
    PatchedCohortApi,
    PatchedRemovePersonRequestApi,
    StaffCohortRecalculateApi,
} from './api.zod.schemas'

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
export const CohortsStaffRecalculateCreateBody = StaffCohortRecalculateApi

export const CohortsCreateBody = CohortApi

export const CohortsUpdateBody = CohortApi

export const CohortsPartialUpdateBody = PatchedCohortApi

export const CohortsAddPersonsToStaticCohortPartialUpdateBody = PatchedAddPersonsToStaticCohortRequestApi

export const CohortsRemovePersonFromStaticCohortPartialUpdateBody = PatchedRemovePersonRequestApi
