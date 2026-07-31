/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import { CoreEventApi, PatchedCoreEventApi } from './api.zod.schemas'

/**
 * CRUD operations for Core Events.
 *
 * Core events are reusable event definitions that can be shared across
 * Marketing analytics, Customer analytics, and Revenue analytics.
 */
export const CoreEventsCreateBody = CoreEventApi

/**
 * CRUD operations for Core Events.
 *
 * Core events are reusable event definitions that can be shared across
 * Marketing analytics, Customer analytics, and Revenue analytics.
 */
export const CoreEventsUpdateBody = CoreEventApi

/**
 * CRUD operations for Core Events.
 *
 * Core events are reusable event definitions that can be shared across
 * Marketing analytics, Customer analytics, and Revenue analytics.
 */
export const CoreEventsPartialUpdateBody = PatchedCoreEventApi
