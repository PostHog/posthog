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

export const CreationTypeEnumApi = zod.enum(['USR', 'GIT']).describe('\* `USR` - user\n\* `GIT` - GitHub')

export type CreationTypeEnumApi = zod.input<typeof CreationTypeEnumApi>
export type CreationTypeEnumApiOutput = zod.output<typeof CreationTypeEnumApi>

export const RoleAtOrganizationEnumApi = zod
    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
    .describe(
        '\* `engineering` - Engineering\n\* `data` - Data\n\* `product` - Product Management\n\* `founder` - Founder\n\* `leadership` - Leadership\n\* `marketing` - Marketing\n\* `sales` - Sales \/ Success\n\* `other` - Other'
    )

export type RoleAtOrganizationEnumApi = zod.input<typeof RoleAtOrganizationEnumApi>
export type RoleAtOrganizationEnumApiOutput = zod.output<typeof RoleAtOrganizationEnumApi>

export const BlankEnumApi = zod.enum([''])

export type BlankEnumApi = zod.input<typeof BlankEnumApi>
export type BlankEnumApiOutput = zod.output<typeof BlankEnumApi>

export const userBasicApiDistinctIdMax = 200

export const userBasicApiFirstNameMax = 150

export const userBasicApiLastNameMax = 150

export const userBasicApiEmailMax = 254

export const UserBasicApi = zod.object({
    id: zod.number(),
    uuid: zod.uuid(),
    distinct_id: zod.string().max(userBasicApiDistinctIdMax).nullish(),
    first_name: zod.string().max(userBasicApiFirstNameMax).optional(),
    last_name: zod.string().max(userBasicApiLastNameMax).optional(),
    email: zod.email().max(userBasicApiEmailMax),
    is_email_verified: zod.boolean().nullish(),
    hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
    role_at_organization: zod.union([RoleAtOrganizationEnumApi, BlankEnumApi, zod.null()]).optional(),
})

export type UserBasicApi = zod.input<typeof UserBasicApi>
export type UserBasicApiOutput = zod.output<typeof UserBasicApi>

export const AnnotationScopeEnumApi = zod
    .enum(['dashboard_item', 'dashboard', 'project', 'organization', 'recording'])
    .describe(
        '\* `dashboard_item` - insight\n\* `dashboard` - dashboard\n\* `project` - project\n\* `organization` - organization\n\* `recording` - recording'
    )

export type AnnotationScopeEnumApi = zod.input<typeof AnnotationScopeEnumApi>
export type AnnotationScopeEnumApiOutput = zod.output<typeof AnnotationScopeEnumApi>

export const annotationApiContentMax = 8192

export const annotationApiEmojiMax = 16

export const AnnotationApi = zod.object({
    id: zod.number(),
    content: zod
        .string()
        .max(annotationApiContentMax)
        .nullish()
        .describe('Annotation text shown on charts to describe the change, release, or incident.'),
    date_marker: zod.iso
        .datetime({ offset: true })
        .nullish()
        .describe('When this annotation happened (ISO 8601 timestamp). Used to position it on charts.'),
    creation_type: CreationTypeEnumApi.optional().describe(
        'Who created this annotation. Use `USR` for user-created notes and `GIT` for bot\/deployment notes.\n\n\* `USR` - user\n\* `GIT` - GitHub'
    ),
    dashboard_item: zod.number().nullish(),
    dashboard_id: zod.number().nullish(),
    dashboard_name: zod.string().nullable(),
    insight_short_id: zod.string().nullable(),
    insight_name: zod.string().nullable(),
    insight_derived_name: zod.string().nullable(),
    created_by: UserBasicApi,
    created_at: zod.iso.datetime({ offset: true }).nullable(),
    updated_at: zod.iso.datetime({ offset: true }),
    deleted: zod
        .boolean()
        .optional()
        .describe('Soft-delete flag. Set to true to hide the annotation, or false to restore it.'),
    scope: AnnotationScopeEnumApi.optional().describe(
        'Annotation visibility scope: `project`, `organization`, `dashboard`, or `dashboard_item`. `recording` is deprecated and rejected.\n\n\* `dashboard_item` - insight\n\* `dashboard` - dashboard\n\* `project` - project\n\* `organization` - organization\n\* `recording` - recording'
    ),
    emoji: zod
        .string()
        .max(annotationApiEmojiMax)
        .nullish()
        .describe('Optional emoji shown in place of the default badge when this annotation is surfaced on a chart.'),
    hidden_in_user_interface: zod
        .boolean()
        .nullish()
        .describe(
            'When true, the annotation is hidden from the PostHog UI (charts and the annotations list) but still readable over the API and MCP. Use for high-frequency markers like deployments that would otherwise crowd the UI. Null (the default) means the annotation is shown.'
        ),
})

export type AnnotationApi = zod.input<typeof AnnotationApi>
export type AnnotationApiOutput = zod.output<typeof AnnotationApi>

export const PaginatedAnnotationListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(AnnotationApi),
})

export type PaginatedAnnotationListApi = zod.input<typeof PaginatedAnnotationListApi>
export type PaginatedAnnotationListApiOutput = zod.output<typeof PaginatedAnnotationListApi>

export const patchedAnnotationApiContentMax = 8192

export const patchedAnnotationApiEmojiMax = 16

export const PatchedAnnotationApi = zod.object({
    id: zod.number().optional(),
    content: zod
        .string()
        .max(patchedAnnotationApiContentMax)
        .nullish()
        .describe('Annotation text shown on charts to describe the change, release, or incident.'),
    date_marker: zod.iso
        .datetime({ offset: true })
        .nullish()
        .describe('When this annotation happened (ISO 8601 timestamp). Used to position it on charts.'),
    creation_type: CreationTypeEnumApi.optional().describe(
        'Who created this annotation. Use `USR` for user-created notes and `GIT` for bot\/deployment notes.\n\n\* `USR` - user\n\* `GIT` - GitHub'
    ),
    dashboard_item: zod.number().nullish(),
    dashboard_id: zod.number().nullish(),
    dashboard_name: zod.string().nullish(),
    insight_short_id: zod.string().nullish(),
    insight_name: zod.string().nullish(),
    insight_derived_name: zod.string().nullish(),
    created_by: UserBasicApi.optional(),
    created_at: zod.iso.datetime({ offset: true }).nullish(),
    updated_at: zod.iso.datetime({ offset: true }).optional(),
    deleted: zod
        .boolean()
        .optional()
        .describe('Soft-delete flag. Set to true to hide the annotation, or false to restore it.'),
    scope: AnnotationScopeEnumApi.optional().describe(
        'Annotation visibility scope: `project`, `organization`, `dashboard`, or `dashboard_item`. `recording` is deprecated and rejected.\n\n\* `dashboard_item` - insight\n\* `dashboard` - dashboard\n\* `project` - project\n\* `organization` - organization\n\* `recording` - recording'
    ),
    emoji: zod
        .string()
        .max(patchedAnnotationApiEmojiMax)
        .nullish()
        .describe('Optional emoji shown in place of the default badge when this annotation is surfaced on a chart.'),
    hidden_in_user_interface: zod
        .boolean()
        .nullish()
        .describe(
            'When true, the annotation is hidden from the PostHog UI (charts and the annotations list) but still readable over the API and MCP. Use for high-frequency markers like deployments that would otherwise crowd the UI. Null (the default) means the annotation is shown.'
        ),
})

export type PatchedAnnotationApi = zod.input<typeof PatchedAnnotationApi>
export type PatchedAnnotationApiOutput = zod.output<typeof PatchedAnnotationApi>
