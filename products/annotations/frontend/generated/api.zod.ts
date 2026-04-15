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
 * Create, Read, Update and Delete annotations. [See docs](https://posthog.com/docs/data/annotations) for more information on annotations.
 */
export const annotationsListResponseResultsItemContentMax = 8192

export const annotationsListResponseResultsItemCreatedByOneDistinctIdMax = 200

export const annotationsListResponseResultsItemCreatedByOneFirstNameMax = 150

export const annotationsListResponseResultsItemCreatedByOneLastNameMax = 150

export const annotationsListResponseResultsItemCreatedByOneEmailMax = 254

export const AnnotationsListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.number(),
            content: zod
                .string()
                .max(annotationsListResponseResultsItemContentMax)
                .nullish()
                .describe('Annotation text shown on charts to describe the change, release, or incident.'),
            date_marker: zod.iso
                .datetime({})
                .nullish()
                .describe('When this annotation happened (ISO 8601 timestamp). Used to position it on charts.'),
            creation_type: zod
                .enum(['USR', 'GIT'])
                .describe('* `USR` - user\n* `GIT` - GitHub')
                .optional()
                .describe(
                    'Who created this annotation. Use `USR` for user-created notes and `GIT` for bot/deployment notes.\n\n* `USR` - user\n* `GIT` - GitHub'
                ),
            dashboard_item: zod.number().nullish(),
            dashboard_id: zod.number().nullish(),
            dashboard_name: zod.string().nullable(),
            insight_short_id: zod.string().nullable(),
            insight_name: zod.string().nullable(),
            insight_derived_name: zod.string().nullable(),
            created_by: zod.object({
                id: zod.number(),
                uuid: zod.uuid(),
                distinct_id: zod.string().max(annotationsListResponseResultsItemCreatedByOneDistinctIdMax).nullish(),
                first_name: zod.string().max(annotationsListResponseResultsItemCreatedByOneFirstNameMax).optional(),
                last_name: zod.string().max(annotationsListResponseResultsItemCreatedByOneLastNameMax).optional(),
                email: zod.email().max(annotationsListResponseResultsItemCreatedByOneEmailMax),
                is_email_verified: zod.boolean().nullish(),
                hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
                role_at_organization: zod
                    .union([
                        zod
                            .enum([
                                'engineering',
                                'data',
                                'product',
                                'founder',
                                'leadership',
                                'marketing',
                                'sales',
                                'other',
                            ])
                            .describe(
                                '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                            ),
                        zod.enum(['']),
                        zod.literal(null),
                    ])
                    .nullish(),
            }),
            created_at: zod.iso.datetime({}).nullable(),
            updated_at: zod.iso.datetime({}),
            deleted: zod
                .boolean()
                .optional()
                .describe('Soft-delete flag. Set to true to hide the annotation, or false to restore it.'),
            scope: zod
                .enum(['dashboard_item', 'dashboard', 'project', 'organization', 'recording'])
                .describe(
                    '* `dashboard_item` - insight\n* `dashboard` - dashboard\n* `project` - project\n* `organization` - organization\n* `recording` - recording'
                )
                .optional()
                .describe(
                    'Annotation visibility scope: `project`, `organization`, `dashboard`, or `dashboard_item`. `recording` is deprecated and rejected.\n\n* `dashboard_item` - insight\n* `dashboard` - dashboard\n* `project` - project\n* `organization` - organization\n* `recording` - recording'
                ),
        })
    ),
})

/**
 * Create, Read, Update and Delete annotations. [See docs](https://posthog.com/docs/data/annotations) for more information on annotations.
 */
export const annotationsCreateBodyContentMax = 8192

export const AnnotationsCreateBody = /* @__PURE__ */ zod.object({
    content: zod
        .string()
        .max(annotationsCreateBodyContentMax)
        .nullish()
        .describe('Annotation text shown on charts to describe the change, release, or incident.'),
    date_marker: zod.iso
        .datetime({})
        .nullish()
        .describe('When this annotation happened (ISO 8601 timestamp). Used to position it on charts.'),
    creation_type: zod
        .enum(['USR', 'GIT'])
        .describe('* `USR` - user\n* `GIT` - GitHub')
        .optional()
        .describe(
            'Who created this annotation. Use `USR` for user-created notes and `GIT` for bot/deployment notes.\n\n* `USR` - user\n* `GIT` - GitHub'
        ),
    dashboard_item: zod.number().nullish(),
    dashboard_id: zod.number().nullish(),
    deleted: zod
        .boolean()
        .optional()
        .describe('Soft-delete flag. Set to true to hide the annotation, or false to restore it.'),
    scope: zod
        .enum(['dashboard_item', 'dashboard', 'project', 'organization', 'recording'])
        .describe(
            '* `dashboard_item` - insight\n* `dashboard` - dashboard\n* `project` - project\n* `organization` - organization\n* `recording` - recording'
        )
        .optional()
        .describe(
            'Annotation visibility scope: `project`, `organization`, `dashboard`, or `dashboard_item`. `recording` is deprecated and rejected.\n\n* `dashboard_item` - insight\n* `dashboard` - dashboard\n* `project` - project\n* `organization` - organization\n* `recording` - recording'
        ),
})

/**
 * Create, Read, Update and Delete annotations. [See docs](https://posthog.com/docs/data/annotations) for more information on annotations.
 */
export const annotationsRetrieveResponseContentMax = 8192

export const annotationsRetrieveResponseCreatedByOneDistinctIdMax = 200

export const annotationsRetrieveResponseCreatedByOneFirstNameMax = 150

export const annotationsRetrieveResponseCreatedByOneLastNameMax = 150

export const annotationsRetrieveResponseCreatedByOneEmailMax = 254

export const AnnotationsRetrieveResponse = /* @__PURE__ */ zod.object({
    id: zod.number(),
    content: zod
        .string()
        .max(annotationsRetrieveResponseContentMax)
        .nullish()
        .describe('Annotation text shown on charts to describe the change, release, or incident.'),
    date_marker: zod.iso
        .datetime({})
        .nullish()
        .describe('When this annotation happened (ISO 8601 timestamp). Used to position it on charts.'),
    creation_type: zod
        .enum(['USR', 'GIT'])
        .describe('* `USR` - user\n* `GIT` - GitHub')
        .optional()
        .describe(
            'Who created this annotation. Use `USR` for user-created notes and `GIT` for bot/deployment notes.\n\n* `USR` - user\n* `GIT` - GitHub'
        ),
    dashboard_item: zod.number().nullish(),
    dashboard_id: zod.number().nullish(),
    dashboard_name: zod.string().nullable(),
    insight_short_id: zod.string().nullable(),
    insight_name: zod.string().nullable(),
    insight_derived_name: zod.string().nullable(),
    created_by: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(annotationsRetrieveResponseCreatedByOneDistinctIdMax).nullish(),
        first_name: zod.string().max(annotationsRetrieveResponseCreatedByOneFirstNameMax).optional(),
        last_name: zod.string().max(annotationsRetrieveResponseCreatedByOneLastNameMax).optional(),
        email: zod.email().max(annotationsRetrieveResponseCreatedByOneEmailMax),
        is_email_verified: zod.boolean().nullish(),
        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
        role_at_organization: zod
            .union([
                zod
                    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
                    .describe(
                        '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                    ),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish(),
    }),
    created_at: zod.iso.datetime({}).nullable(),
    updated_at: zod.iso.datetime({}),
    deleted: zod
        .boolean()
        .optional()
        .describe('Soft-delete flag. Set to true to hide the annotation, or false to restore it.'),
    scope: zod
        .enum(['dashboard_item', 'dashboard', 'project', 'organization', 'recording'])
        .describe(
            '* `dashboard_item` - insight\n* `dashboard` - dashboard\n* `project` - project\n* `organization` - organization\n* `recording` - recording'
        )
        .optional()
        .describe(
            'Annotation visibility scope: `project`, `organization`, `dashboard`, or `dashboard_item`. `recording` is deprecated and rejected.\n\n* `dashboard_item` - insight\n* `dashboard` - dashboard\n* `project` - project\n* `organization` - organization\n* `recording` - recording'
        ),
})

/**
 * Create, Read, Update and Delete annotations. [See docs](https://posthog.com/docs/data/annotations) for more information on annotations.
 */
export const annotationsUpdateBodyContentMax = 8192

export const AnnotationsUpdateBody = /* @__PURE__ */ zod.object({
    content: zod
        .string()
        .max(annotationsUpdateBodyContentMax)
        .nullish()
        .describe('Annotation text shown on charts to describe the change, release, or incident.'),
    date_marker: zod.iso
        .datetime({})
        .nullish()
        .describe('When this annotation happened (ISO 8601 timestamp). Used to position it on charts.'),
    creation_type: zod
        .enum(['USR', 'GIT'])
        .describe('* `USR` - user\n* `GIT` - GitHub')
        .optional()
        .describe(
            'Who created this annotation. Use `USR` for user-created notes and `GIT` for bot/deployment notes.\n\n* `USR` - user\n* `GIT` - GitHub'
        ),
    dashboard_item: zod.number().nullish(),
    dashboard_id: zod.number().nullish(),
    deleted: zod
        .boolean()
        .optional()
        .describe('Soft-delete flag. Set to true to hide the annotation, or false to restore it.'),
    scope: zod
        .enum(['dashboard_item', 'dashboard', 'project', 'organization', 'recording'])
        .describe(
            '* `dashboard_item` - insight\n* `dashboard` - dashboard\n* `project` - project\n* `organization` - organization\n* `recording` - recording'
        )
        .optional()
        .describe(
            'Annotation visibility scope: `project`, `organization`, `dashboard`, or `dashboard_item`. `recording` is deprecated and rejected.\n\n* `dashboard_item` - insight\n* `dashboard` - dashboard\n* `project` - project\n* `organization` - organization\n* `recording` - recording'
        ),
})

export const annotationsUpdateResponseContentMax = 8192

export const annotationsUpdateResponseCreatedByOneDistinctIdMax = 200

export const annotationsUpdateResponseCreatedByOneFirstNameMax = 150

export const annotationsUpdateResponseCreatedByOneLastNameMax = 150

export const annotationsUpdateResponseCreatedByOneEmailMax = 254

export const AnnotationsUpdateResponse = /* @__PURE__ */ zod.object({
    id: zod.number(),
    content: zod
        .string()
        .max(annotationsUpdateResponseContentMax)
        .nullish()
        .describe('Annotation text shown on charts to describe the change, release, or incident.'),
    date_marker: zod.iso
        .datetime({})
        .nullish()
        .describe('When this annotation happened (ISO 8601 timestamp). Used to position it on charts.'),
    creation_type: zod
        .enum(['USR', 'GIT'])
        .describe('* `USR` - user\n* `GIT` - GitHub')
        .optional()
        .describe(
            'Who created this annotation. Use `USR` for user-created notes and `GIT` for bot/deployment notes.\n\n* `USR` - user\n* `GIT` - GitHub'
        ),
    dashboard_item: zod.number().nullish(),
    dashboard_id: zod.number().nullish(),
    dashboard_name: zod.string().nullable(),
    insight_short_id: zod.string().nullable(),
    insight_name: zod.string().nullable(),
    insight_derived_name: zod.string().nullable(),
    created_by: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(annotationsUpdateResponseCreatedByOneDistinctIdMax).nullish(),
        first_name: zod.string().max(annotationsUpdateResponseCreatedByOneFirstNameMax).optional(),
        last_name: zod.string().max(annotationsUpdateResponseCreatedByOneLastNameMax).optional(),
        email: zod.email().max(annotationsUpdateResponseCreatedByOneEmailMax),
        is_email_verified: zod.boolean().nullish(),
        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
        role_at_organization: zod
            .union([
                zod
                    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
                    .describe(
                        '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                    ),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish(),
    }),
    created_at: zod.iso.datetime({}).nullable(),
    updated_at: zod.iso.datetime({}),
    deleted: zod
        .boolean()
        .optional()
        .describe('Soft-delete flag. Set to true to hide the annotation, or false to restore it.'),
    scope: zod
        .enum(['dashboard_item', 'dashboard', 'project', 'organization', 'recording'])
        .describe(
            '* `dashboard_item` - insight\n* `dashboard` - dashboard\n* `project` - project\n* `organization` - organization\n* `recording` - recording'
        )
        .optional()
        .describe(
            'Annotation visibility scope: `project`, `organization`, `dashboard`, or `dashboard_item`. `recording` is deprecated and rejected.\n\n* `dashboard_item` - insight\n* `dashboard` - dashboard\n* `project` - project\n* `organization` - organization\n* `recording` - recording'
        ),
})

/**
 * Create, Read, Update and Delete annotations. [See docs](https://posthog.com/docs/data/annotations) for more information on annotations.
 */
export const annotationsPartialUpdateBodyContentMax = 8192

export const AnnotationsPartialUpdateBody = /* @__PURE__ */ zod.object({
    content: zod
        .string()
        .max(annotationsPartialUpdateBodyContentMax)
        .nullish()
        .describe('Annotation text shown on charts to describe the change, release, or incident.'),
    date_marker: zod.iso
        .datetime({})
        .nullish()
        .describe('When this annotation happened (ISO 8601 timestamp). Used to position it on charts.'),
    creation_type: zod
        .enum(['USR', 'GIT'])
        .describe('* `USR` - user\n* `GIT` - GitHub')
        .optional()
        .describe(
            'Who created this annotation. Use `USR` for user-created notes and `GIT` for bot/deployment notes.\n\n* `USR` - user\n* `GIT` - GitHub'
        ),
    dashboard_item: zod.number().nullish(),
    dashboard_id: zod.number().nullish(),
    deleted: zod
        .boolean()
        .optional()
        .describe('Soft-delete flag. Set to true to hide the annotation, or false to restore it.'),
    scope: zod
        .enum(['dashboard_item', 'dashboard', 'project', 'organization', 'recording'])
        .describe(
            '* `dashboard_item` - insight\n* `dashboard` - dashboard\n* `project` - project\n* `organization` - organization\n* `recording` - recording'
        )
        .optional()
        .describe(
            'Annotation visibility scope: `project`, `organization`, `dashboard`, or `dashboard_item`. `recording` is deprecated and rejected.\n\n* `dashboard_item` - insight\n* `dashboard` - dashboard\n* `project` - project\n* `organization` - organization\n* `recording` - recording'
        ),
})

export const annotationsPartialUpdateResponseContentMax = 8192

export const annotationsPartialUpdateResponseCreatedByOneDistinctIdMax = 200

export const annotationsPartialUpdateResponseCreatedByOneFirstNameMax = 150

export const annotationsPartialUpdateResponseCreatedByOneLastNameMax = 150

export const annotationsPartialUpdateResponseCreatedByOneEmailMax = 254

export const AnnotationsPartialUpdateResponse = /* @__PURE__ */ zod.object({
    id: zod.number(),
    content: zod
        .string()
        .max(annotationsPartialUpdateResponseContentMax)
        .nullish()
        .describe('Annotation text shown on charts to describe the change, release, or incident.'),
    date_marker: zod.iso
        .datetime({})
        .nullish()
        .describe('When this annotation happened (ISO 8601 timestamp). Used to position it on charts.'),
    creation_type: zod
        .enum(['USR', 'GIT'])
        .describe('* `USR` - user\n* `GIT` - GitHub')
        .optional()
        .describe(
            'Who created this annotation. Use `USR` for user-created notes and `GIT` for bot/deployment notes.\n\n* `USR` - user\n* `GIT` - GitHub'
        ),
    dashboard_item: zod.number().nullish(),
    dashboard_id: zod.number().nullish(),
    dashboard_name: zod.string().nullable(),
    insight_short_id: zod.string().nullable(),
    insight_name: zod.string().nullable(),
    insight_derived_name: zod.string().nullable(),
    created_by: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(annotationsPartialUpdateResponseCreatedByOneDistinctIdMax).nullish(),
        first_name: zod.string().max(annotationsPartialUpdateResponseCreatedByOneFirstNameMax).optional(),
        last_name: zod.string().max(annotationsPartialUpdateResponseCreatedByOneLastNameMax).optional(),
        email: zod.email().max(annotationsPartialUpdateResponseCreatedByOneEmailMax),
        is_email_verified: zod.boolean().nullish(),
        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
        role_at_organization: zod
            .union([
                zod
                    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
                    .describe(
                        '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                    ),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish(),
    }),
    created_at: zod.iso.datetime({}).nullable(),
    updated_at: zod.iso.datetime({}),
    deleted: zod
        .boolean()
        .optional()
        .describe('Soft-delete flag. Set to true to hide the annotation, or false to restore it.'),
    scope: zod
        .enum(['dashboard_item', 'dashboard', 'project', 'organization', 'recording'])
        .describe(
            '* `dashboard_item` - insight\n* `dashboard` - dashboard\n* `project` - project\n* `organization` - organization\n* `recording` - recording'
        )
        .optional()
        .describe(
            'Annotation visibility scope: `project`, `organization`, `dashboard`, or `dashboard_item`. `recording` is deprecated and rejected.\n\n* `dashboard_item` - insight\n* `dashboard` - dashboard\n* `project` - project\n* `organization` - organization\n* `recording` - recording'
        ),
})
