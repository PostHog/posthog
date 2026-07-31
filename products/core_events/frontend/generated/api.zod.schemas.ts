/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import { z as zod } from 'zod'

export const CoreEventCategoryEnumApi = zod
    .enum(['acquisition', 'activation', 'monetization', 'expansion', 'referral', 'retention', 'churn', 'reactivation'])
    .describe(
        '\* `acquisition` - Acquisition\n\* `activation` - Activation\n\* `monetization` - Monetization\n\* `expansion` - Expansion\n\* `referral` - Referral\n\* `retention` - Retention\n\* `churn` - Churn\n\* `reactivation` - Reactivation'
    )

export type CoreEventCategoryEnumApi = zod.input<typeof CoreEventCategoryEnumApi>
export type CoreEventCategoryEnumApiOutput = zod.output<typeof CoreEventCategoryEnumApi>

export const coreEventApiNameMax = 255

export const CoreEventApi = zod.object({
    id: zod.uuid(),
    name: zod.string().max(coreEventApiNameMax).describe('Display name for this core event'),
    description: zod.string().optional().describe('Optional description'),
    category: CoreEventCategoryEnumApi.describe(
        'Lifecycle category for this core event\n\n\* `acquisition` - Acquisition\n\* `activation` - Activation\n\* `monetization` - Monetization\n\* `expansion` - Expansion\n\* `referral` - Referral\n\* `retention` - Retention\n\* `churn` - Churn\n\* `reactivation` - Reactivation'
    ),
    filter: zod.unknown().describe('Filter configuration - event, action, or data warehouse node'),
    created_at: zod.iso.datetime({ offset: true }),
    updated_at: zod.iso.datetime({ offset: true }),
})

export type CoreEventApi = zod.input<typeof CoreEventApi>
export type CoreEventApiOutput = zod.output<typeof CoreEventApi>

export const PaginatedCoreEventListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(CoreEventApi),
})

export type PaginatedCoreEventListApi = zod.input<typeof PaginatedCoreEventListApi>
export type PaginatedCoreEventListApiOutput = zod.output<typeof PaginatedCoreEventListApi>

export const patchedCoreEventApiNameMax = 255

export const PatchedCoreEventApi = zod.object({
    id: zod.uuid().optional(),
    name: zod.string().max(patchedCoreEventApiNameMax).optional().describe('Display name for this core event'),
    description: zod.string().optional().describe('Optional description'),
    category: CoreEventCategoryEnumApi.optional().describe(
        'Lifecycle category for this core event\n\n\* `acquisition` - Acquisition\n\* `activation` - Activation\n\* `monetization` - Monetization\n\* `expansion` - Expansion\n\* `referral` - Referral\n\* `retention` - Retention\n\* `churn` - Churn\n\* `reactivation` - Reactivation'
    ),
    filter: zod.unknown().optional().describe('Filter configuration - event, action, or data warehouse node'),
    created_at: zod.iso.datetime({ offset: true }).optional(),
    updated_at: zod.iso.datetime({ offset: true }).optional(),
})

export type PatchedCoreEventApi = zod.input<typeof PatchedCoreEventApi>
export type PatchedCoreEventApiOutput = zod.output<typeof PatchedCoreEventApi>
