/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import { AlertApi, AlertSimulateApi, PatchedAlertApi } from './api.zod.schemas'

export const AlertsCreateBody = AlertApi

export const AlertsUpdateBody = AlertApi

export const AlertsPartialUpdateBody = PatchedAlertApi

/**
 * Simulate a detector on an insight's historical data. Read-only — no AlertCheck records are created.
 */
export const AlertsSimulateCreateBody = AlertSimulateApi
