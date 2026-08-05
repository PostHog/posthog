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
export const annotationsCreateBodyContentMax = 8192

export const annotationsCreateBodyEmojiMax = 16

export const AnnotationsCreateBody = /* @__PURE__ */ zod.object({
    content: zod
        .string()
        .max(annotationsCreateBodyContentMax)
        .nullish()
        .describe('Annotation text shown on charts to describe the change, release, or incident.'),
    date_marker: zod.iso
        .datetime({ offset: true })
        .nullish()
        .describe('When this annotation happened (ISO 8601 timestamp). Used to position it on charts.'),
    creation_type: zod
        .enum(['USR', 'GIT'])
        .describe('\* `USR` - user\n\* `GIT` - GitHub')
        .optional()
        .describe(
            'Who created this annotation. Use `USR` for user-created notes and `GIT` for bot\/deployment notes.\n\n\* `USR` - user\n\* `GIT` - GitHub'
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
            '\* `dashboard_item` - insight\n\* `dashboard` - dashboard\n\* `project` - project\n\* `organization` - organization\n\* `recording` - recording'
        )
        .optional()
        .describe(
            'Annotation visibility scope: `project`, `organization`, `dashboard`, or `dashboard_item`. `recording` is deprecated and rejected.\n\n\* `dashboard_item` - insight\n\* `dashboard` - dashboard\n\* `project` - project\n\* `organization` - organization\n\* `recording` - recording'
        ),
    emoji: zod
        .string()
        .max(annotationsCreateBodyEmojiMax)
        .nullish()
        .describe('Optional emoji shown in place of the default badge when this annotation is surfaced on a chart.'),
    hidden_in_user_interface: zod
        .boolean()
        .nullish()
        .describe(
            'When true, the annotation is hidden from the PostHog UI (charts and the annotations list) but still readable over the API and MCP. Use for high-frequency markers like deployments that would otherwise crowd the UI. Null (the default) means the annotation is shown.'
        ),
})

/**
 * Create, Read, Update and Delete annotations. [See docs](https://posthog.com/docs/data/annotations) for more information on annotations.
 */
export const annotationsUpdateBodyContentMax = 8192

export const annotationsUpdateBodyEmojiMax = 16

export const AnnotationsUpdateBody = /* @__PURE__ */ zod.object({
    content: zod
        .string()
        .max(annotationsUpdateBodyContentMax)
        .nullish()
        .describe('Annotation text shown on charts to describe the change, release, or incident.'),
    date_marker: zod.iso
        .datetime({ offset: true })
        .nullish()
        .describe('When this annotation happened (ISO 8601 timestamp). Used to position it on charts.'),
    creation_type: zod
        .enum(['USR', 'GIT'])
        .describe('\* `USR` - user\n\* `GIT` - GitHub')
        .optional()
        .describe(
            'Who created this annotation. Use `USR` for user-created notes and `GIT` for bot\/deployment notes.\n\n\* `USR` - user\n\* `GIT` - GitHub'
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
            '\* `dashboard_item` - insight\n\* `dashboard` - dashboard\n\* `project` - project\n\* `organization` - organization\n\* `recording` - recording'
        )
        .optional()
        .describe(
            'Annotation visibility scope: `project`, `organization`, `dashboard`, or `dashboard_item`. `recording` is deprecated and rejected.\n\n\* `dashboard_item` - insight\n\* `dashboard` - dashboard\n\* `project` - project\n\* `organization` - organization\n\* `recording` - recording'
        ),
    emoji: zod
        .string()
        .max(annotationsUpdateBodyEmojiMax)
        .nullish()
        .describe('Optional emoji shown in place of the default badge when this annotation is surfaced on a chart.'),
    hidden_in_user_interface: zod
        .boolean()
        .nullish()
        .describe(
            'When true, the annotation is hidden from the PostHog UI (charts and the annotations list) but still readable over the API and MCP. Use for high-frequency markers like deployments that would otherwise crowd the UI. Null (the default) means the annotation is shown.'
        ),
})

/**
 * Create, Read, Update and Delete annotations. [See docs](https://posthog.com/docs/data/annotations) for more information on annotations.
 */
export const annotationsPartialUpdateBodyContentMax = 8192

export const annotationsPartialUpdateBodyEmojiMax = 16

export const AnnotationsPartialUpdateBody = /* @__PURE__ */ zod.object({
    content: zod
        .string()
        .max(annotationsPartialUpdateBodyContentMax)
        .nullish()
        .describe('Annotation text shown on charts to describe the change, release, or incident.'),
    date_marker: zod.iso
        .datetime({ offset: true })
        .nullish()
        .describe('When this annotation happened (ISO 8601 timestamp). Used to position it on charts.'),
    creation_type: zod
        .enum(['USR', 'GIT'])
        .describe('\* `USR` - user\n\* `GIT` - GitHub')
        .optional()
        .describe(
            'Who created this annotation. Use `USR` for user-created notes and `GIT` for bot\/deployment notes.\n\n\* `USR` - user\n\* `GIT` - GitHub'
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
            '\* `dashboard_item` - insight\n\* `dashboard` - dashboard\n\* `project` - project\n\* `organization` - organization\n\* `recording` - recording'
        )
        .optional()
        .describe(
            'Annotation visibility scope: `project`, `organization`, `dashboard`, or `dashboard_item`. `recording` is deprecated and rejected.\n\n\* `dashboard_item` - insight\n\* `dashboard` - dashboard\n\* `project` - project\n\* `organization` - organization\n\* `recording` - recording'
        ),
    emoji: zod
        .string()
        .max(annotationsPartialUpdateBodyEmojiMax)
        .nullish()
        .describe('Optional emoji shown in place of the default badge when this annotation is surfaced on a chart.'),
    hidden_in_user_interface: zod
        .boolean()
        .nullish()
        .describe(
            'When true, the annotation is hidden from the PostHog UI (charts and the annotations list) but still readable over the API and MCP. Use for high-frequency markers like deployments that would otherwise crowd the UI. Null (the default) means the annotation is shown.'
        ),
})
