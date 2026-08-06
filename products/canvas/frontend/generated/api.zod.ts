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
 * Create a new, empty canvas in a channel; give it source by publishing a project.
 */
export const canvasesCreateBodyNameMax = 400

export const canvasesCreateBodyTemplateIdDefault = `freeform`
export const canvasesCreateBodyTemplateIdMax = 64

export const CanvasesCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().max(canvasesCreateBodyNameMax).describe('Display name for the canvas.'),
        channel_id: zod.uuid().describe('Id of the channel the canvas belongs to.'),
        template_id: zod
            .string()
            .max(canvasesCreateBodyTemplateIdMax)
            .default(canvasesCreateBodyTemplateIdDefault)
            .describe('Canvas template identifier.'),
    })
    .describe('Payload for creating a new, empty canvas in a channel.')

/**
 * Update canvas metadata (name, author context, pin, generation-task pointer).
 */
export const canvasesPartialUpdateBodyNameMax = 400

export const CanvasesPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().max(canvasesPartialUpdateBodyNameMax).optional().describe('Updated display name.'),
        context: zod.string().optional().describe('Updated author context markdown.'),
        pinned: zod.boolean().optional().describe('Whether the canvas is pinned in its channel.'),
        generation_task_id: zod
            .uuid()
            .nullish()
            .describe('Task currently generating this canvas, or null to clear it.'),
    })
    .describe('Writable canvas fields: metadata only — source changes go through publish\/edit.')

/**
 * Apply a lifecycle action (retry, pin, unpin, cancel) to one build.
 */
export const CanvasesBuildActionCreateBody = /* @__PURE__ */ zod.object({
    action: zod
        .enum(['retry', 'pin', 'unpin', 'cancel'])
        .describe('\* `retry` - retry\n\* `pin` - pin\n\* `unpin` - unpin\n\* `cancel` - cancel'),
    build_id: zod.uuid(),
})

/**
 * Publish per-file edits against the canvas's current source project.
 *
 * Diff-aware alternative to sending the complete project: each operation
 * sets a file's content or (content null) deletes it, applied to the head
 * the caller read. `expected_current_version_id` is mandatory here —
 * relative edits against an unverified base could silently merge into
 * someone else's newer work.
 */
export const canvasesEditCreateBodyNameMax = 400

export const CanvasesEditCreateBody = /* @__PURE__ */ zod
    .object({
        operations: zod
            .array(
                zod
                    .object({
                        path: zod
                            .string()
                            .describe(
                                'Project-relative path of the file to write or delete (e.g. \"src\/canvas.tsx\").'
                            ),
                        content: zod
                            .string()
                            .nullish()
                            .describe("The file's complete new content. Null (or omitted) deletes the file."),
                    })
                    .describe("One per-file edit: set a file's content, or delete it.")
            )
            .describe("Edits applied in order to the canvas's current source project."),
        prompt: zod
            .string()
            .optional()
            .describe('Short description of the change, stored on the appended version history entry.'),
        name: zod
            .string()
            .max(canvasesEditCreateBodyNameMax)
            .optional()
            .describe('Optional new display name for the canvas.'),
        expected_current_version_id: zod
            .string()
            .nullable()
            .describe(
                'Required optimistic-concurrency guard: the current_version_id the edits are based on (null when the canvas has never been published). Diff edits against a moved head are rejected with 409 version_conflict — they cannot be published unguarded.'
            ),
    })
    .describe("Payload for publishing per-file edits against the canvas's current source.")

/**
 * Publish a complete source project as the canvas's new head version.
 *
 * Validation errors reject the publish (400) and leave the canvas
 * untouched; a stale `expected_current_version_id` is rejected with 409.
 * A successful publish queues a server-side build.
 */
export const canvasesPublishCreateBodyProjectOneAssetsContentMax = 2796204

export const canvasesPublishCreateBodyProjectOneAssetsContentRegExp = new RegExp(
    '^(?:[A-Za-z0-9+\/]{4})\*(?:[A-Za-z0-9+\/]{2}==|[A-Za-z0-9+\/]{3}=)?$'
)
export const canvasesPublishCreateBodyProjectOneCapabilitiesOnePosthogInsightsItemMax = 128

export const canvasesPublishCreateBodyProjectOneCapabilitiesOnePosthogInsightsMax = 100

export const canvasesPublishCreateBodyProjectOneCapabilitiesOnePosthogCaptureEventsItemMax = 200

export const canvasesPublishCreateBodyProjectOneCapabilitiesOnePosthogCaptureEventsMax = 100

export const canvasesPublishCreateBodyProjectOneCapabilitiesOneNetworkOriginsItemMax = 2048

export const canvasesPublishCreateBodyProjectOneCapabilitiesOneNetworkOriginsMax = 20

export const canvasesPublishCreateBodyNameMax = 400

export const CanvasesPublishCreateBody = /* @__PURE__ */ zod
    .object({
        project: zod
            .object({
                schemaVersion: zod.number().describe('Source-project schema version. Currently always 1.'),
                files: zod
                    .record(zod.string(), zod.string())
                    .describe("Project files keyed by relative path (forward slashes, no '..')."),
                assets: zod
                    .record(
                        zod.string(),
                        zod.object({
                            encoding: zod.enum(['base64']).describe('\* `base64` - base64'),
                            contentType: zod
                                .enum([
                                    'image/png',
                                    'image/jpeg',
                                    'image/gif',
                                    'image/webp',
                                    'image/svg+xml',
                                    'font/woff',
                                    'font/woff2',
                                    'application/wasm',
                                    'application/octet-stream',
                                ])
                                .describe(
                                    '\* `image\/png` - image\/png\n\* `image\/jpeg` - image\/jpeg\n\* `image\/gif` - image\/gif\n\* `image\/webp` - image\/webp\n\* `image\/svg+xml` - image\/svg+xml\n\* `font\/woff` - font\/woff\n\* `font\/woff2` - font\/woff2\n\* `application\/wasm` - application\/wasm\n\* `application\/octet-stream` - application\/octet-stream'
                                ),
                            content: zod
                                .string()
                                .max(canvasesPublishCreateBodyProjectOneAssetsContentMax)
                                .regex(canvasesPublishCreateBodyProjectOneAssetsContentRegExp),
                        })
                    )
                    .optional()
                    .describe('Optional base64-encoded binary assets keyed by safe project-relative paths.'),
                entryHtml: zod.string().describe('The project\'s entry HTML file. Currently always \"index.html\".'),
                dependencies: zod
                    .record(zod.string(), zod.string())
                    .optional()
                    .describe(
                        'Exact-version dependencies, restricted to the platform-supported set (react, react-dom, @posthog\/quill, recharts, lucide-react, dayjs) at their pinned versions.'
                    ),
                canvasSdkVersion: zod
                    .string()
                    .optional()
                    .describe('Version of the host-injected `ph` canvas SDK the project targets.'),
                capabilities: zod
                    .object({
                        posthog: zod.object({
                            insights: zod
                                .array(
                                    zod
                                        .string()
                                        .max(canvasesPublishCreateBodyProjectOneCapabilitiesOnePosthogInsightsItemMax)
                                )
                                .max(canvasesPublishCreateBodyProjectOneCapabilitiesOnePosthogInsightsMax),
                            inlineQueries: zod.boolean(),
                            captureEvents: zod
                                .array(
                                    zod
                                        .string()
                                        .max(
                                            canvasesPublishCreateBodyProjectOneCapabilitiesOnePosthogCaptureEventsItemMax
                                        )
                                )
                                .max(canvasesPublishCreateBodyProjectOneCapabilitiesOnePosthogCaptureEventsMax),
                        }),
                        network: zod.object({
                            origins: zod
                                .array(
                                    zod
                                        .url()
                                        .max(canvasesPublishCreateBodyProjectOneCapabilitiesOneNetworkOriginsItemMax)
                                )
                                .max(canvasesPublishCreateBodyProjectOneCapabilitiesOneNetworkOriginsMax),
                        }),
                    })
                    .optional()
                    .describe(
                        'Bounded capabilities frozen into the built artifact. Declare every insight short id the canvas loads, every event it captures, and inlineQueries when it runs ad-hoc HogQL — the host enforces these at runtime and validation rejects undeclared `ph` calls.'
                    ),
            })
            .describe("A canvas's multi-file source project — the canonical write format for canvas source.")
            .describe('The complete source project to publish.'),
        prompt: zod
            .string()
            .optional()
            .describe('Short description of the change, stored on the appended version history entry.'),
        name: zod
            .string()
            .max(canvasesPublishCreateBodyNameMax)
            .optional()
            .describe('Optional new display name for the canvas.'),
        expected_current_version_id: zod
            .string()
            .nullish()
            .describe(
                'Optimistic-concurrency guard: the current_version_id the publisher based its edits on (null when it read a canvas with no versions yet). When the canvas has since moved past it the publish is rejected with a 409 version_conflict instead of overwriting the newer head. Omit to publish unguarded.'
            ),
    })
    .describe('Payload for publishing a complete canvas source project.')

/**
 * Move the canvas's head back to an existing source version and rebuild it.
 */
export const CanvasesRevertCreateBody = /* @__PURE__ */ zod
    .object({
        version_id: zod.uuid().describe('Id of the source version to make the head again.'),
        expected_current_version_id: zod
            .uuid()
            .nullable()
            .describe('Current source version observed before requesting the revert.'),
    })
    .describe("Payload for reverting the canvas's head to an existing source version.")

/**
 * Validate a candidate source project without publishing it. Side-effect free.
 */
export const canvasesValidateCreateBodyProjectOneAssetsContentMax = 2796204

export const canvasesValidateCreateBodyProjectOneAssetsContentRegExp = new RegExp(
    '^(?:[A-Za-z0-9+\/]{4})\*(?:[A-Za-z0-9+\/]{2}==|[A-Za-z0-9+\/]{3}=)?$'
)
export const canvasesValidateCreateBodyProjectOneCapabilitiesOnePosthogInsightsItemMax = 128

export const canvasesValidateCreateBodyProjectOneCapabilitiesOnePosthogInsightsMax = 100

export const canvasesValidateCreateBodyProjectOneCapabilitiesOnePosthogCaptureEventsItemMax = 200

export const canvasesValidateCreateBodyProjectOneCapabilitiesOnePosthogCaptureEventsMax = 100

export const canvasesValidateCreateBodyProjectOneCapabilitiesOneNetworkOriginsItemMax = 2048

export const canvasesValidateCreateBodyProjectOneCapabilitiesOneNetworkOriginsMax = 20

export const CanvasesValidateCreateBody = /* @__PURE__ */ zod
    .object({
        project: zod
            .object({
                schemaVersion: zod.number().describe('Source-project schema version. Currently always 1.'),
                files: zod
                    .record(zod.string(), zod.string())
                    .describe("Project files keyed by relative path (forward slashes, no '..')."),
                assets: zod
                    .record(
                        zod.string(),
                        zod.object({
                            encoding: zod.enum(['base64']).describe('\* `base64` - base64'),
                            contentType: zod
                                .enum([
                                    'image/png',
                                    'image/jpeg',
                                    'image/gif',
                                    'image/webp',
                                    'image/svg+xml',
                                    'font/woff',
                                    'font/woff2',
                                    'application/wasm',
                                    'application/octet-stream',
                                ])
                                .describe(
                                    '\* `image\/png` - image\/png\n\* `image\/jpeg` - image\/jpeg\n\* `image\/gif` - image\/gif\n\* `image\/webp` - image\/webp\n\* `image\/svg+xml` - image\/svg+xml\n\* `font\/woff` - font\/woff\n\* `font\/woff2` - font\/woff2\n\* `application\/wasm` - application\/wasm\n\* `application\/octet-stream` - application\/octet-stream'
                                ),
                            content: zod
                                .string()
                                .max(canvasesValidateCreateBodyProjectOneAssetsContentMax)
                                .regex(canvasesValidateCreateBodyProjectOneAssetsContentRegExp),
                        })
                    )
                    .optional()
                    .describe('Optional base64-encoded binary assets keyed by safe project-relative paths.'),
                entryHtml: zod.string().describe('The project\'s entry HTML file. Currently always \"index.html\".'),
                dependencies: zod
                    .record(zod.string(), zod.string())
                    .optional()
                    .describe(
                        'Exact-version dependencies, restricted to the platform-supported set (react, react-dom, @posthog\/quill, recharts, lucide-react, dayjs) at their pinned versions.'
                    ),
                canvasSdkVersion: zod
                    .string()
                    .optional()
                    .describe('Version of the host-injected `ph` canvas SDK the project targets.'),
                capabilities: zod
                    .object({
                        posthog: zod.object({
                            insights: zod
                                .array(
                                    zod
                                        .string()
                                        .max(canvasesValidateCreateBodyProjectOneCapabilitiesOnePosthogInsightsItemMax)
                                )
                                .max(canvasesValidateCreateBodyProjectOneCapabilitiesOnePosthogInsightsMax),
                            inlineQueries: zod.boolean(),
                            captureEvents: zod
                                .array(
                                    zod
                                        .string()
                                        .max(
                                            canvasesValidateCreateBodyProjectOneCapabilitiesOnePosthogCaptureEventsItemMax
                                        )
                                )
                                .max(canvasesValidateCreateBodyProjectOneCapabilitiesOnePosthogCaptureEventsMax),
                        }),
                        network: zod.object({
                            origins: zod
                                .array(
                                    zod
                                        .url()
                                        .max(canvasesValidateCreateBodyProjectOneCapabilitiesOneNetworkOriginsItemMax)
                                )
                                .max(canvasesValidateCreateBodyProjectOneCapabilitiesOneNetworkOriginsMax),
                        }),
                    })
                    .optional()
                    .describe(
                        'Bounded capabilities frozen into the built artifact. Declare every insight short id the canvas loads, every event it captures, and inlineQueries when it runs ad-hoc HogQL — the host enforces these at runtime and validation rejects undeclared `ph` calls.'
                    ),
            })
            .describe("A canvas's multi-file source project — the canonical write format for canvas source.")
            .describe('The candidate source project to validate.'),
    })
    .describe('Payload for validating a candidate source project without publishing it.')
