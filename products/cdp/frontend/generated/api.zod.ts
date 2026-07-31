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
    HogFunctionApi,
    HogFunctionInvocationApi,
    HogInvocationRerunRequestApi,
    PatchedHogFunctionApi,
    PatchedHogFunctionRearrangeApi,
} from './api.zod.schemas'

export const HogFunctionsCreateBody = HogFunctionApi

export const HogFunctionsUpdateBody = HogFunctionApi

export const HogFunctionsPartialUpdateBody = PatchedHogFunctionApi

export const HogFunctionsEnableBackfillsCreateBody = HogFunctionApi

export const HogFunctionsInvocationsCreateBody = HogFunctionInvocationApi

/**
 * Rerun past invocations of this hog function from their stored payloads.
 *
 * The CDP worker reads matching rows from the `hog_invocation_results`
 * ClickHouse table, rehydrates the invocation from the stored
 * `invocation_globals`, and re-enqueues onto cyclotron. Each rerun
 * run reuses the original `invocation_id` with `is_retry=1` set on the
 * new lifecycle row so the UI can surface that it was a rerun.
 *
 * Only types a cyclotron worker executes (`TYPES_THAT_CAN_RERUN`) can be
 * rerun: rerun re-enqueues onto the cyclotron hog queue, and other types
 * run elsewhere (source webhooks inline in the cdp-api HTTP handler,
 * transformations during ingestion, `site_*` transpiled to client-side
 * JS). A re-enqueued invocation of one of those would never drain and
 * wedges the partition, so a rerun of a non-rerunnable type is rejected
 * with a 400 here.
 *
 * Because rerun replays historical event/person/group data, it requires
 * `person:read` and `group:read` on top of `hog_function:write`.
 */
export const HogFunctionsRerunCreateBody = HogInvocationRerunRequestApi

/**
 * Update the execution order of multiple HogFunctions.
 */
export const HogFunctionsRearrangePartialUpdateBody = PatchedHogFunctionRearrangeApi
