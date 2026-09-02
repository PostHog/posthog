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

export const canvasesCreateBodyKindDefault = `freeform`
export const canvasesCreateBodyDescriptionDefault = ``
export const canvasesCreateBodyTemplateIdDefault = `freeform`
export const canvasesCreateBodyTemplateIdMax = 64

export const CanvasesCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().max(canvasesCreateBodyNameMax).describe('Display name for the canvas.'),
        channel_id: zod.uuid().describe('Id of the channel the canvas belongs to.'),
        kind: zod
            .enum(['freeform', 'grid', 'component'])
            .describe('\* `freeform` - freeform\n\* `grid` - grid\n\* `component` - component')
            .default(canvasesCreateBodyKindDefault)
            .describe(
                "What to create: 'freeform' (a standalone app), 'component' (a reusable widget for grids — its published project must declare a `component` placement contract), or 'grid' (a composition of components, edited through the layout endpoints).\n\n\* `freeform` - freeform\n\* `grid` - grid\n\* `component` - component"
            ),
        description: zod
            .string()
            .default(canvasesCreateBodyDescriptionDefault)
            .describe(
                'Short prose describing the canvas. For components this is the store-search text agents match against — say what the widget shows and what its config controls.'
            ),
        template_id: zod
            .string()
            .max(canvasesCreateBodyTemplateIdMax)
            .default(canvasesCreateBodyTemplateIdDefault)
            .describe('Canvas template identifier.'),
    })
    .describe('Payload for creating a new, empty canvas in a channel.')

/**
 * Update canvas metadata, including the space it belongs to.
 */
export const canvasesPartialUpdateBodyNameMax = 400

export const CanvasesPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().max(canvasesPartialUpdateBodyNameMax).optional().describe('Updated display name.'),
        context: zod.string().optional().describe('Updated author context markdown.'),
        description: zod
            .string()
            .optional()
            .describe('Updated canvas description (for components, the store-search text).'),
        channel_id: zod.uuid().optional().describe('Id of the space the canvas belongs to.'),
        pinned: zod.boolean().optional().describe('Whether the canvas is pinned in its channel.'),
        generation_task_id: zod
            .uuid()
            .nullish()
            .describe('Task currently generating this canvas, or null to clear it.'),
    })
    .describe('Writable canvas fields: metadata only — source changes go through publish\/edit.')

/**
 * Invoke one registered action verb as the viewer.
 *
 * The canvas must declare the verb in capabilities.posthog.actions (the
 * reviewed permission boundary); the write itself runs with the viewer's
 * own permissions, exactly as if they acted in the app.
 */
export const canvasesActionsInvokeBodyVerbMax = 64

export const CanvasesActionsInvokeBody = /* @__PURE__ */ zod
    .object({
        verb: zod
            .string()
            .max(canvasesActionsInvokeBodyVerbMax)
            .describe("Registered verb to invoke, e.g. 'tasks.create'."),
        payload: zod
            .record(zod.string(), zod.unknown())
            .optional()
            .describe("Verb-specific arguments, validated against the verb's payload schema."),
    })
    .describe('Payload for invoking one action verb.')

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
 * Stage a complete source project as a draft version and build it, without publishing.
 *
 * The draft gets the same validation, versioning, and server-side build as
 * a publish, but the canvas's head and live build never move, so nothing
 * changes for viewers. Promote the version with `promote` to make it live.
 * The response reports how the draft's declared capabilities widen the
 * current head's, so growth in access can be reviewed before it ships.
 * No version guard applies: a draft conflicts with nothing.
 */
export const canvasesDraftCreateBodyProjectOneAssetsContentMax = 2796204

export const canvasesDraftCreateBodyProjectOneAssetsContentRegExp = new RegExp(
    '^(?:[A-Za-z0-9+\/]{4})\*(?:[A-Za-z0-9+\/]{2}==|[A-Za-z0-9+\/]{3}=)?$'
)
export const canvasesDraftCreateBodyProjectOneComponentOneSizeOneDefaultWMax = 12

export const canvasesDraftCreateBodyProjectOneComponentOneSizeOneDefaultHMax = 40

export const canvasesDraftCreateBodyProjectOneComponentOneSizeOneMinWMax = 12

export const canvasesDraftCreateBodyProjectOneComponentOneSizeOneMinHMax = 40

export const canvasesDraftCreateBodyProjectOneComponentOneSizeOneMaxWMax = 12

export const canvasesDraftCreateBodyProjectOneComponentOneSizeOneMaxHMax = 40

export const canvasesDraftCreateBodyProjectOneCapabilitiesOnePosthogInsightsItemMax = 128

export const canvasesDraftCreateBodyProjectOneCapabilitiesOnePosthogInsightsMax = 100

export const canvasesDraftCreateBodyProjectOneCapabilitiesOnePosthogCaptureEventsItemMax = 200

export const canvasesDraftCreateBodyProjectOneCapabilitiesOnePosthogCaptureEventsMax = 100

export const canvasesDraftCreateBodyProjectOneCapabilitiesOnePosthogStateMax = 2

export const canvasesDraftCreateBodyProjectOneCapabilitiesOnePosthogActionsItemMax = 64

export const canvasesDraftCreateBodyProjectOneCapabilitiesOnePosthogActionsMax = 32

export const canvasesDraftCreateBodyProjectOneCapabilitiesOnePosthogAgentRequestsDefault = false
export const canvasesDraftCreateBodyProjectOneCapabilitiesOneNetworkOriginsItemMax = 2048

export const canvasesDraftCreateBodyProjectOneCapabilitiesOneNetworkOriginsMax = 20

export const CanvasesDraftCreateBody = /* @__PURE__ */ zod
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
                                .max(canvasesDraftCreateBodyProjectOneAssetsContentMax)
                                .regex(canvasesDraftCreateBodyProjectOneAssetsContentRegExp),
                        })
                    )
                    .optional()
                    .describe('Optional base64-encoded binary assets keyed by safe project-relative paths.'),
                entryHtml: zod.string().describe('The project\'s entry HTML file. Currently always \"index.html\".'),
                dependencies: zod
                    .record(zod.string(), zod.string())
                    .optional()
                    .describe(
                        'Exact-version dependencies, restricted to the platform-supported set at its pinned versions.'
                    ),
                canvasSdkVersion: zod
                    .string()
                    .optional()
                    .describe('Version of the host-injected `ph` canvas SDK the project targets.'),
                component: zod
                    .object({
                        size: zod
                            .object({
                                defaultW: zod
                                    .number()
                                    .min(1)
                                    .max(canvasesDraftCreateBodyProjectOneComponentOneSizeOneDefaultWMax)
                                    .describe('Width a new placement starts at, in grid columns.'),
                                defaultH: zod
                                    .number()
                                    .min(1)
                                    .max(canvasesDraftCreateBodyProjectOneComponentOneSizeOneDefaultHMax)
                                    .describe('Height a new placement starts at, in grid rows.'),
                                minW: zod
                                    .number()
                                    .min(1)
                                    .max(canvasesDraftCreateBodyProjectOneComponentOneSizeOneMinWMax)
                                    .describe('Narrowest width the component renders usefully at.'),
                                minH: zod
                                    .number()
                                    .min(1)
                                    .max(canvasesDraftCreateBodyProjectOneComponentOneSizeOneMinHMax)
                                    .describe('Shortest height the component renders usefully at.'),
                                maxW: zod
                                    .number()
                                    .min(1)
                                    .max(canvasesDraftCreateBodyProjectOneComponentOneSizeOneMaxWMax)
                                    .optional()
                                    .describe("Widest allowed width; omit for no cap below the grid's width."),
                                maxH: zod
                                    .number()
                                    .min(1)
                                    .max(canvasesDraftCreateBodyProjectOneComponentOneSizeOneMaxHMax)
                                    .optional()
                                    .describe('Tallest allowed height; omit for no cap.'),
                            })
                            .describe("A component's grid-size contract, in grid units.")
                            .describe('Grid-size contract for placements of this component.'),
                        configSchema: zod
                            .record(zod.string(), zod.unknown())
                            .optional()
                            .describe(
                                'JSON Schema (\"type\": \"object\") for a placement\'s config. The host validates each placement\'s config against it and passes the validated object to the widget at mount.'
                            ),
                    })
                    .describe("A component's placement contract: how grid canvases may place and configure it.")
                    .optional()
                    .describe(
                        'Placement contract, required for (and only allowed on) component-kind canvases: the grid size the component takes and the JSON Schema of its per-placement config.'
                    ),
                capabilities: zod
                    .object({
                        posthog: zod.object({
                            insights: zod
                                .array(
                                    zod
                                        .string()
                                        .max(canvasesDraftCreateBodyProjectOneCapabilitiesOnePosthogInsightsItemMax)
                                )
                                .max(canvasesDraftCreateBodyProjectOneCapabilitiesOnePosthogInsightsMax),
                            inlineQueries: zod.boolean(),
                            captureEvents: zod
                                .array(
                                    zod
                                        .string()
                                        .max(
                                            canvasesDraftCreateBodyProjectOneCapabilitiesOnePosthogCaptureEventsItemMax
                                        )
                                )
                                .max(canvasesDraftCreateBodyProjectOneCapabilitiesOnePosthogCaptureEventsMax),
                            state: zod
                                .array(zod.enum(['user', 'shared']).describe('\* `user` - user\n\* `shared` - shared'))
                                .max(canvasesDraftCreateBodyProjectOneCapabilitiesOnePosthogStateMax)
                                .optional()
                                .describe(
                                    "State scopes the canvas may use via ph.state: 'user' (private to each viewer) and\/or 'shared' (one value per canvas, team-visible)."
                                ),
                            actions: zod
                                .array(
                                    zod
                                        .string()
                                        .max(canvasesDraftCreateBodyProjectOneCapabilitiesOnePosthogActionsItemMax)
                                )
                                .max(canvasesDraftCreateBodyProjectOneCapabilitiesOnePosthogActionsMax)
                                .optional()
                                .describe(
                                    "Registered action verbs the canvas may invoke via ph.actions (e.g. 'annotations.create', 'tasks.create'). Each executes as the viewer; declaring one shows it in the promote review."
                                ),
                            agentRequests: zod
                                .boolean()
                                .default(canvasesDraftCreateBodyProjectOneCapabilitiesOnePosthogAgentRequestsDefault),
                        }),
                        network: zod.object({
                            origins: zod
                                .array(
                                    zod.url().max(canvasesDraftCreateBodyProjectOneCapabilitiesOneNetworkOriginsItemMax)
                                )
                                .max(canvasesDraftCreateBodyProjectOneCapabilitiesOneNetworkOriginsMax),
                        }),
                    })
                    .optional()
                    .describe(
                        'Bounded capabilities frozen into the built artifact. Declare every insight short id the canvas loads, every event it captures, and inlineQueries when it runs ad-hoc HogQL — the host enforces these at runtime and validation rejects undeclared `ph` calls. Network origins must be exact HTTPS origins. Data fetched by canvas code can be sent to those origins.'
                    ),
            })
            .describe("A canvas's multi-file source project — the canonical write format for canvas source.")
            .describe('The complete source project to stage as a draft.'),
        prompt: zod
            .string()
            .optional()
            .describe("Short description of the change, stored on the draft's version history entry."),
    })
    .describe('Payload for staging a complete source project as a draft build.')

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
 * Apply surgical operations to the grid canvas's current layout.
 *
 * The default write path for both the editor and agents: add, move,
 * resize, fill, or remove one placement without resending the layout.
 * `expected_current_version_id` is mandatory so an agent filling a box
 * and a user rearranging widgets cannot overwrite each other.
 */
export const canvasesLayoutPatchCreateBodyOperationsItemGridOneRowHeightMin = 24
export const canvasesLayoutPatchCreateBodyOperationsItemGridOneRowHeightMax = 400

export const canvasesLayoutPatchCreateBodyOperationsItemGridOneGapMin = 0
export const canvasesLayoutPatchCreateBodyOperationsItemGridOneGapMax = 48

export const canvasesLayoutPatchCreateBodyOperationsItemPlacementOneIdMax = 64

export const canvasesLayoutPatchCreateBodyOperationsItemPlacementOneIdRegExp = new RegExp('^[A-Za-z0-9_-]{1,64}$')
export const canvasesLayoutPatchCreateBodyOperationsItemPlacementOneXMin = 0

export const canvasesLayoutPatchCreateBodyOperationsItemPlacementOneYMin = 0

export const canvasesLayoutPatchCreateBodyOperationsItemPlacementOnePromptMax = 10000

export const canvasesLayoutPatchCreateBodyOperationsItemIdMax = 64

export const canvasesLayoutPatchCreateBodyOperationsItemChangesOneXMin = 0

export const canvasesLayoutPatchCreateBodyOperationsItemChangesOneYMin = 0

export const canvasesLayoutPatchCreateBodyOperationsItemChangesOnePromptMax = 10000

export const CanvasesLayoutPatchCreateBody = /* @__PURE__ */ zod
    .object({
        operations: zod
            .array(
                zod
                    .object({
                        op: zod
                            .enum(['set_grid', 'add_placement', 'update_placement', 'remove_placement'])
                            .describe(
                                '\* `set_grid` - set_grid\n\* `add_placement` - add_placement\n\* `update_placement` - update_placement\n\* `remove_placement` - remove_placement'
                            )
                            .describe(
                                'The operation to apply.\n\n\* `set_grid` - set_grid\n\* `add_placement` - add_placement\n\* `update_placement` - update_placement\n\* `remove_placement` - remove_placement'
                            ),
                        grid: zod
                            .object({
                                columns: zod
                                    .union([
                                        zod.literal(4),
                                        zod.literal(6),
                                        zod.literal(8),
                                        zod.literal(10),
                                        zod.literal(12),
                                    ])
                                    .describe('\* `4` - 4\n\* `6` - 6\n\* `8` - 8\n\* `10` - 10\n\* `12` - 12')
                                    .describe(
                                        'Grid width in columns. One of 4, 6, 8, 10, or 12.\n\n\* `4` - 4\n\* `6` - 6\n\* `8` - 8\n\* `10` - 10\n\* `12` - 12'
                                    ),
                                rowHeight: zod
                                    .number()
                                    .min(canvasesLayoutPatchCreateBodyOperationsItemGridOneRowHeightMin)
                                    .max(canvasesLayoutPatchCreateBodyOperationsItemGridOneRowHeightMax)
                                    .describe('Height of one grid row, in pixels.'),
                                gap: zod
                                    .number()
                                    .min(canvasesLayoutPatchCreateBodyOperationsItemGridOneGapMin)
                                    .max(canvasesLayoutPatchCreateBodyOperationsItemGridOneGapMax)
                                    .describe('Gap between placements, in pixels.'),
                            })
                            .describe('The grid a grid canvas lays its placements out on.')
                            .optional()
                            .describe('For set_grid: the new grid definition.'),
                        placement: zod
                            .object({
                                id: zod
                                    .string()
                                    .max(canvasesLayoutPatchCreateBodyOperationsItemPlacementOneIdMax)
                                    .regex(canvasesLayoutPatchCreateBodyOperationsItemPlacementOneIdRegExp)
                                    .describe(
                                        "Stable placement id, unique within the layout. 1-64 characters of letters, digits, '_', or '-'."
                                    ),
                                status: zod
                                    .enum(['pending', 'generating', 'live', 'failed'])
                                    .describe(
                                        '\* `pending` - pending\n\* `generating` - generating\n\* `live` - live\n\* `failed` - failed'
                                    )
                                    .describe(
                                        "Placement lifecycle: 'pending' (box drawn, no prompt yet), 'generating' (an agent task is filling it), 'live' (renders its component), 'failed' (generation failed; re-prompt or remove).\n\n\* `pending` - pending\n\* `generating` - generating\n\* `live` - live\n\* `failed` - failed"
                                    ),
                                component: zod
                                    .string()
                                    .nullish()
                                    .describe(
                                        'Id of the component canvas this placement renders. Required once the placement is live.'
                                    ),
                                version: zod
                                    .string()
                                    .nullish()
                                    .describe(
                                        'Component version to render: \"latest\" (the default — follows the component\'s published build) or a pinned source version id.'
                                    ),
                                x: zod
                                    .number()
                                    .min(canvasesLayoutPatchCreateBodyOperationsItemPlacementOneXMin)
                                    .describe('Left edge, in grid columns (0-based).'),
                                y: zod
                                    .number()
                                    .min(canvasesLayoutPatchCreateBodyOperationsItemPlacementOneYMin)
                                    .describe('Top edge, in grid rows (0-based).'),
                                w: zod.number().min(1).describe('Width, in grid columns.'),
                                h: zod.number().min(1).describe('Height, in grid rows.'),
                                config: zod
                                    .record(zod.string(), zod.unknown())
                                    .nullish()
                                    .describe(
                                        "Per-placement settings, validated against the component's configSchema."
                                    ),
                                prompt: zod
                                    .string()
                                    .max(canvasesLayoutPatchCreateBodyOperationsItemPlacementOnePromptMax)
                                    .nullish()
                                    .describe(
                                        'For pending\/generating\/failed placements: what the user asked this box to become.'
                                    ),
                                generationTaskId: zod
                                    .string()
                                    .nullish()
                                    .describe(
                                        'Id of the agent task currently filling this placement, when one is running.'
                                    ),
                            })
                            .describe('One placed widget on a grid canvas.')
                            .optional()
                            .describe('For add_placement: the placement to add.'),
                        id: zod
                            .string()
                            .max(canvasesLayoutPatchCreateBodyOperationsItemIdMax)
                            .optional()
                            .describe('For update_placement\/remove_placement: the target placement id.'),
                        changes: zod
                            .object({
                                status: zod
                                    .enum(['pending', 'generating', 'live', 'failed'])
                                    .describe(
                                        '\* `pending` - pending\n\* `generating` - generating\n\* `live` - live\n\* `failed` - failed'
                                    )
                                    .optional()
                                    .describe(
                                        "Placement lifecycle: 'pending' (box drawn, no prompt yet), 'generating' (an agent task is filling it), 'live' (renders its component), 'failed' (generation failed; re-prompt or remove).\n\n\* `pending` - pending\n\* `generating` - generating\n\* `live` - live\n\* `failed` - failed"
                                    ),
                                component: zod
                                    .string()
                                    .nullish()
                                    .describe(
                                        'Id of the component canvas this placement renders. Required once the placement is live.'
                                    ),
                                version: zod
                                    .string()
                                    .nullish()
                                    .describe(
                                        'Component version to render: \"latest\" (the default — follows the component\'s published build) or a pinned source version id.'
                                    ),
                                x: zod
                                    .number()
                                    .min(canvasesLayoutPatchCreateBodyOperationsItemChangesOneXMin)
                                    .optional()
                                    .describe('Left edge, in grid columns (0-based).'),
                                y: zod
                                    .number()
                                    .min(canvasesLayoutPatchCreateBodyOperationsItemChangesOneYMin)
                                    .optional()
                                    .describe('Top edge, in grid rows (0-based).'),
                                w: zod.number().min(1).optional().describe('Width, in grid columns.'),
                                h: zod.number().min(1).optional().describe('Height, in grid rows.'),
                                config: zod
                                    .record(zod.string(), zod.unknown())
                                    .nullish()
                                    .describe(
                                        "Per-placement settings, validated against the component's configSchema."
                                    ),
                                prompt: zod
                                    .string()
                                    .max(canvasesLayoutPatchCreateBodyOperationsItemChangesOnePromptMax)
                                    .nullish()
                                    .describe(
                                        'For pending\/generating\/failed placements: what the user asked this box to become.'
                                    ),
                                generationTaskId: zod
                                    .string()
                                    .nullish()
                                    .describe(
                                        'Id of the agent task currently filling this placement, when one is running.'
                                    ),
                            })
                            .describe('Fields to merge into an existing placement (all optional; id cannot change).')
                            .optional()
                            .describe('For update_placement: the fields to merge into the placement.'),
                    })
                    .describe('One surgical layout operation.')
            )
            .describe("Operations applied in order to the canvas's current layout, at most 64."),
        prompt: zod
            .string()
            .optional()
            .describe('Short description of the change, stored on the appended version history entry.'),
        expected_current_version_id: zod
            .string()
            .nullable()
            .describe(
                'Required optimistic-concurrency guard: the current_version_id the operations are based on (null when the canvas has no layout versions yet). A moved head is rejected with 409 version_conflict — patches cannot apply unguarded.'
            ),
    })
    .describe("Payload for applying surgical operations to the canvas's current layout.")

/**
 * Publish a complete layout document as the grid canvas's new head version.
 *
 * Layout is data, not code: the new version is live immediately, with no
 * build. Validation errors reject the publish (400) and leave the canvas
 * untouched; a stale `expected_current_version_id` is rejected with 409.
 */
export const canvasesLayoutPublishCreateBodyLayoutOneGridOneRowHeightMin = 24
export const canvasesLayoutPublishCreateBodyLayoutOneGridOneRowHeightMax = 400

export const canvasesLayoutPublishCreateBodyLayoutOneGridOneGapMin = 0
export const canvasesLayoutPublishCreateBodyLayoutOneGridOneGapMax = 48

export const canvasesLayoutPublishCreateBodyLayoutOnePlacementsItemIdMax = 64

export const canvasesLayoutPublishCreateBodyLayoutOnePlacementsItemIdRegExp = new RegExp('^[A-Za-z0-9_-]{1,64}$')
export const canvasesLayoutPublishCreateBodyLayoutOnePlacementsItemXMin = 0

export const canvasesLayoutPublishCreateBodyLayoutOnePlacementsItemYMin = 0

export const canvasesLayoutPublishCreateBodyLayoutOnePlacementsItemPromptMax = 10000

export const CanvasesLayoutPublishCreateBody = /* @__PURE__ */ zod
    .object({
        layout: zod
            .object({
                schemaVersion: zod
                    .literal(1)
                    .describe('\* `1` - 1')
                    .describe('Layout schema version. Currently always 1.\n\n\* `1` - 1'),
                grid: zod
                    .object({
                        columns: zod
                            .union([zod.literal(4), zod.literal(6), zod.literal(8), zod.literal(10), zod.literal(12)])
                            .describe('\* `4` - 4\n\* `6` - 6\n\* `8` - 8\n\* `10` - 10\n\* `12` - 12')
                            .describe(
                                'Grid width in columns. One of 4, 6, 8, 10, or 12.\n\n\* `4` - 4\n\* `6` - 6\n\* `8` - 8\n\* `10` - 10\n\* `12` - 12'
                            ),
                        rowHeight: zod
                            .number()
                            .min(canvasesLayoutPublishCreateBodyLayoutOneGridOneRowHeightMin)
                            .max(canvasesLayoutPublishCreateBodyLayoutOneGridOneRowHeightMax)
                            .describe('Height of one grid row, in pixels.'),
                        gap: zod
                            .number()
                            .min(canvasesLayoutPublishCreateBodyLayoutOneGridOneGapMin)
                            .max(canvasesLayoutPublishCreateBodyLayoutOneGridOneGapMax)
                            .describe('Gap between placements, in pixels.'),
                    })
                    .describe('The grid a grid canvas lays its placements out on.')
                    .describe('The grid placements are laid out on.'),
                placements: zod
                    .array(
                        zod
                            .object({
                                id: zod
                                    .string()
                                    .max(canvasesLayoutPublishCreateBodyLayoutOnePlacementsItemIdMax)
                                    .regex(canvasesLayoutPublishCreateBodyLayoutOnePlacementsItemIdRegExp)
                                    .describe(
                                        "Stable placement id, unique within the layout. 1-64 characters of letters, digits, '_', or '-'."
                                    ),
                                status: zod
                                    .enum(['pending', 'generating', 'live', 'failed'])
                                    .describe(
                                        '\* `pending` - pending\n\* `generating` - generating\n\* `live` - live\n\* `failed` - failed'
                                    )
                                    .describe(
                                        "Placement lifecycle: 'pending' (box drawn, no prompt yet), 'generating' (an agent task is filling it), 'live' (renders its component), 'failed' (generation failed; re-prompt or remove).\n\n\* `pending` - pending\n\* `generating` - generating\n\* `live` - live\n\* `failed` - failed"
                                    ),
                                component: zod
                                    .string()
                                    .nullish()
                                    .describe(
                                        'Id of the component canvas this placement renders. Required once the placement is live.'
                                    ),
                                version: zod
                                    .string()
                                    .nullish()
                                    .describe(
                                        'Component version to render: \"latest\" (the default — follows the component\'s published build) or a pinned source version id.'
                                    ),
                                x: zod
                                    .number()
                                    .min(canvasesLayoutPublishCreateBodyLayoutOnePlacementsItemXMin)
                                    .describe('Left edge, in grid columns (0-based).'),
                                y: zod
                                    .number()
                                    .min(canvasesLayoutPublishCreateBodyLayoutOnePlacementsItemYMin)
                                    .describe('Top edge, in grid rows (0-based).'),
                                w: zod.number().min(1).describe('Width, in grid columns.'),
                                h: zod.number().min(1).describe('Height, in grid rows.'),
                                config: zod
                                    .record(zod.string(), zod.unknown())
                                    .nullish()
                                    .describe(
                                        "Per-placement settings, validated against the component's configSchema."
                                    ),
                                prompt: zod
                                    .string()
                                    .max(canvasesLayoutPublishCreateBodyLayoutOnePlacementsItemPromptMax)
                                    .nullish()
                                    .describe(
                                        'For pending\/generating\/failed placements: what the user asked this box to become.'
                                    ),
                                generationTaskId: zod
                                    .string()
                                    .nullish()
                                    .describe(
                                        'Id of the agent task currently filling this placement, when one is running.'
                                    ),
                            })
                            .describe('One placed widget on a grid canvas.')
                    )
                    .describe('The placed widgets, at most 24. Placements may not overlap or extend past the grid.'),
            })
            .describe("A grid canvas's layout document — its entire 'source'.")
            .describe('The complete layout document to publish.'),
        prompt: zod
            .string()
            .optional()
            .describe('Short description of the change, stored on the appended version history entry.'),
        expected_current_version_id: zod
            .string()
            .nullish()
            .describe(
                'Optimistic-concurrency guard: the current_version_id the layout was based on (null when the canvas has no versions yet). A moved head is rejected with 409 version_conflict. Omit to publish unguarded.'
            ),
    })
    .describe('Payload for publishing a complete layout document.')

/**
 * Make a draft version the canvas's live head.
 *
 * A draft whose build is ready goes live immediately, with no rebuild;
 * otherwise a fresh build is queued. Returns that build.
 */
export const CanvasesPromoteCreateBody = /* @__PURE__ */ zod
    .object({
        version_id: zod.uuid().describe('Id of the draft source version to make live.'),
        expected_current_version_id: zod
            .uuid()
            .nullable()
            .describe(
                'Current source version observed before requesting the promote (null when the canvas has never been published). A moved head is rejected with 409 version_conflict.'
            ),
    })
    .describe("Payload for promoting a draft version to the canvas's live head.")

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
export const canvasesPublishCreateBodyProjectOneComponentOneSizeOneDefaultWMax = 12

export const canvasesPublishCreateBodyProjectOneComponentOneSizeOneDefaultHMax = 40

export const canvasesPublishCreateBodyProjectOneComponentOneSizeOneMinWMax = 12

export const canvasesPublishCreateBodyProjectOneComponentOneSizeOneMinHMax = 40

export const canvasesPublishCreateBodyProjectOneComponentOneSizeOneMaxWMax = 12

export const canvasesPublishCreateBodyProjectOneComponentOneSizeOneMaxHMax = 40

export const canvasesPublishCreateBodyProjectOneCapabilitiesOnePosthogInsightsItemMax = 128

export const canvasesPublishCreateBodyProjectOneCapabilitiesOnePosthogInsightsMax = 100

export const canvasesPublishCreateBodyProjectOneCapabilitiesOnePosthogCaptureEventsItemMax = 200

export const canvasesPublishCreateBodyProjectOneCapabilitiesOnePosthogCaptureEventsMax = 100

export const canvasesPublishCreateBodyProjectOneCapabilitiesOnePosthogStateMax = 2

export const canvasesPublishCreateBodyProjectOneCapabilitiesOnePosthogActionsItemMax = 64

export const canvasesPublishCreateBodyProjectOneCapabilitiesOnePosthogActionsMax = 32

export const canvasesPublishCreateBodyProjectOneCapabilitiesOnePosthogAgentRequestsDefault = false
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
                        'Exact-version dependencies, restricted to the platform-supported set at its pinned versions.'
                    ),
                canvasSdkVersion: zod
                    .string()
                    .optional()
                    .describe('Version of the host-injected `ph` canvas SDK the project targets.'),
                component: zod
                    .object({
                        size: zod
                            .object({
                                defaultW: zod
                                    .number()
                                    .min(1)
                                    .max(canvasesPublishCreateBodyProjectOneComponentOneSizeOneDefaultWMax)
                                    .describe('Width a new placement starts at, in grid columns.'),
                                defaultH: zod
                                    .number()
                                    .min(1)
                                    .max(canvasesPublishCreateBodyProjectOneComponentOneSizeOneDefaultHMax)
                                    .describe('Height a new placement starts at, in grid rows.'),
                                minW: zod
                                    .number()
                                    .min(1)
                                    .max(canvasesPublishCreateBodyProjectOneComponentOneSizeOneMinWMax)
                                    .describe('Narrowest width the component renders usefully at.'),
                                minH: zod
                                    .number()
                                    .min(1)
                                    .max(canvasesPublishCreateBodyProjectOneComponentOneSizeOneMinHMax)
                                    .describe('Shortest height the component renders usefully at.'),
                                maxW: zod
                                    .number()
                                    .min(1)
                                    .max(canvasesPublishCreateBodyProjectOneComponentOneSizeOneMaxWMax)
                                    .optional()
                                    .describe("Widest allowed width; omit for no cap below the grid's width."),
                                maxH: zod
                                    .number()
                                    .min(1)
                                    .max(canvasesPublishCreateBodyProjectOneComponentOneSizeOneMaxHMax)
                                    .optional()
                                    .describe('Tallest allowed height; omit for no cap.'),
                            })
                            .describe("A component's grid-size contract, in grid units.")
                            .describe('Grid-size contract for placements of this component.'),
                        configSchema: zod
                            .record(zod.string(), zod.unknown())
                            .optional()
                            .describe(
                                'JSON Schema (\"type\": \"object\") for a placement\'s config. The host validates each placement\'s config against it and passes the validated object to the widget at mount.'
                            ),
                    })
                    .describe("A component's placement contract: how grid canvases may place and configure it.")
                    .optional()
                    .describe(
                        'Placement contract, required for (and only allowed on) component-kind canvases: the grid size the component takes and the JSON Schema of its per-placement config.'
                    ),
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
                            state: zod
                                .array(zod.enum(['user', 'shared']).describe('\* `user` - user\n\* `shared` - shared'))
                                .max(canvasesPublishCreateBodyProjectOneCapabilitiesOnePosthogStateMax)
                                .optional()
                                .describe(
                                    "State scopes the canvas may use via ph.state: 'user' (private to each viewer) and\/or 'shared' (one value per canvas, team-visible)."
                                ),
                            actions: zod
                                .array(
                                    zod
                                        .string()
                                        .max(canvasesPublishCreateBodyProjectOneCapabilitiesOnePosthogActionsItemMax)
                                )
                                .max(canvasesPublishCreateBodyProjectOneCapabilitiesOnePosthogActionsMax)
                                .optional()
                                .describe(
                                    "Registered action verbs the canvas may invoke via ph.actions (e.g. 'annotations.create', 'tasks.create'). Each executes as the viewer; declaring one shows it in the promote review."
                                ),
                            agentRequests: zod
                                .boolean()
                                .default(canvasesPublishCreateBodyProjectOneCapabilitiesOnePosthogAgentRequestsDefault),
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
                        'Bounded capabilities frozen into the built artifact. Declare every insight short id the canvas loads, every event it captures, and inlineQueries when it runs ad-hoc HogQL — the host enforces these at runtime and validation rejects undeclared `ph` calls. Network origins must be exact HTTPS origins. Data fetched by canvas code can be sent to those origins.'
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
 * Queue a build for the current source version without changing source or metadata.
 */
export const CanvasesPublishCurrentVersionCreateBody = /* @__PURE__ */ zod.object({
    expected_current_version_id: zod
        .uuid()
        .describe('Current source version to publish. A changed head returns a 409 version_conflict.'),
})

/**
 * Report a runtime error observed while rendering a canvas build.
 *
 * Files the report in the authoring task's thread (deduped per build and
 * error type) so the canvas's agent can be asked to fix it. Reports never
 * start an agent run by themselves — dispatch is `request_fix`. Only the
 * error class crosses the server; full messages and stacks stay
 * client-side because rendering sessions can carry viewer data.
 */
export const canvasesReportErrorCreateBodyErrorTypeMax = 64

export const CanvasesReportErrorCreateBody = /* @__PURE__ */ zod
    .object({
        build_id: zod.uuid().describe('Id of the build that was rendering when the error occurred.'),
        error_type: zod
            .string()
            .max(canvasesReportErrorCreateBodyErrorTypeMax)
            .describe(
                "Error class name only, for example TypeError. Values that are not a plain class-name identifier are recorded as 'unknown'. Full error messages and stack traces must stay client-side."
            ),
    })
    .describe('Payload for reporting a runtime error observed while rendering a canvas build.')

/**
 * Route a viewer-approved change request to the canvas's authoring task.
 */
export const canvasesRequestAgentCreateBodyPromptMax = 10000

export const CanvasesRequestAgentCreateBody = /* @__PURE__ */ zod
    .object({
        prompt: zod
            .string()
            .max(canvasesRequestAgentCreateBodyPromptMax)
            .describe('Exact change request the viewer reviewed and approved in the trusted host dialog.'),
    })
    .describe("A viewer-approved request for the canvas's authoring agent.")

/**
 * Wake the canvas's authoring agent to fix a failing build or runtime error.
 *
 * Starts (or signals) an agent run on the authoring task, instructed to
 * stage the fix as a draft the user reviews and promotes. This is the
 * human-initiated dispatch step behind error reports; it spends agent
 * compute, so it never fires automatically, and only the authoring
 * task's creator may dispatch — the run executes with their credentials.
 */
export const canvasesRequestFixCreateBodyErrorTypeMax = 64

export const CanvasesRequestFixCreateBody = /* @__PURE__ */ zod
    .object({
        build_id: zod.uuid().describe('Id of the failing or erroring build the fix should address.'),
        error_type: zod
            .string()
            .max(canvasesRequestFixCreateBodyErrorTypeMax)
            .optional()
            .describe(
                'Error class from the runtime report, when fixing a runtime error. Omit for a failed build; its diagnostics are read server-side.'
            ),
    })
    .describe("Payload for asking the canvas's authoring agent to fix a failing build or runtime error.")

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
 * Write one key of the canvas's runtime state, or delete it with a null value.
 */
export const canvasesStateSetBodyKeyMax = 200

export const CanvasesStateSetBody = /* @__PURE__ */ zod
    .object({
        scope: zod
            .enum(['user', 'shared'])
            .describe('\* `user` - user\n\* `shared` - shared')
            .describe(
                'Scope to write into; the canvas must declare it in capabilities.posthog.state.\n\n\* `user` - user\n\* `shared` - shared'
            ),
        key: zod.string().max(canvasesStateSetBodyKeyMax).describe('Key to write, unique within its scope.'),
        value: zod.unknown().describe('JSON value to store (at most 64 KB serialized), or null to delete the key.'),
    })
    .describe("Payload for writing (or deleting) one key of a canvas's runtime state.")

/**
 * Validate a candidate source project without publishing it. Side-effect free.
 */
export const canvasesValidateCreateBodyProjectOneAssetsContentMax = 2796204

export const canvasesValidateCreateBodyProjectOneAssetsContentRegExp = new RegExp(
    '^(?:[A-Za-z0-9+\/]{4})\*(?:[A-Za-z0-9+\/]{2}==|[A-Za-z0-9+\/]{3}=)?$'
)
export const canvasesValidateCreateBodyProjectOneComponentOneSizeOneDefaultWMax = 12

export const canvasesValidateCreateBodyProjectOneComponentOneSizeOneDefaultHMax = 40

export const canvasesValidateCreateBodyProjectOneComponentOneSizeOneMinWMax = 12

export const canvasesValidateCreateBodyProjectOneComponentOneSizeOneMinHMax = 40

export const canvasesValidateCreateBodyProjectOneComponentOneSizeOneMaxWMax = 12

export const canvasesValidateCreateBodyProjectOneComponentOneSizeOneMaxHMax = 40

export const canvasesValidateCreateBodyProjectOneCapabilitiesOnePosthogInsightsItemMax = 128

export const canvasesValidateCreateBodyProjectOneCapabilitiesOnePosthogInsightsMax = 100

export const canvasesValidateCreateBodyProjectOneCapabilitiesOnePosthogCaptureEventsItemMax = 200

export const canvasesValidateCreateBodyProjectOneCapabilitiesOnePosthogCaptureEventsMax = 100

export const canvasesValidateCreateBodyProjectOneCapabilitiesOnePosthogStateMax = 2

export const canvasesValidateCreateBodyProjectOneCapabilitiesOnePosthogActionsItemMax = 64

export const canvasesValidateCreateBodyProjectOneCapabilitiesOnePosthogActionsMax = 32

export const canvasesValidateCreateBodyProjectOneCapabilitiesOnePosthogAgentRequestsDefault = false
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
                        'Exact-version dependencies, restricted to the platform-supported set at its pinned versions.'
                    ),
                canvasSdkVersion: zod
                    .string()
                    .optional()
                    .describe('Version of the host-injected `ph` canvas SDK the project targets.'),
                component: zod
                    .object({
                        size: zod
                            .object({
                                defaultW: zod
                                    .number()
                                    .min(1)
                                    .max(canvasesValidateCreateBodyProjectOneComponentOneSizeOneDefaultWMax)
                                    .describe('Width a new placement starts at, in grid columns.'),
                                defaultH: zod
                                    .number()
                                    .min(1)
                                    .max(canvasesValidateCreateBodyProjectOneComponentOneSizeOneDefaultHMax)
                                    .describe('Height a new placement starts at, in grid rows.'),
                                minW: zod
                                    .number()
                                    .min(1)
                                    .max(canvasesValidateCreateBodyProjectOneComponentOneSizeOneMinWMax)
                                    .describe('Narrowest width the component renders usefully at.'),
                                minH: zod
                                    .number()
                                    .min(1)
                                    .max(canvasesValidateCreateBodyProjectOneComponentOneSizeOneMinHMax)
                                    .describe('Shortest height the component renders usefully at.'),
                                maxW: zod
                                    .number()
                                    .min(1)
                                    .max(canvasesValidateCreateBodyProjectOneComponentOneSizeOneMaxWMax)
                                    .optional()
                                    .describe("Widest allowed width; omit for no cap below the grid's width."),
                                maxH: zod
                                    .number()
                                    .min(1)
                                    .max(canvasesValidateCreateBodyProjectOneComponentOneSizeOneMaxHMax)
                                    .optional()
                                    .describe('Tallest allowed height; omit for no cap.'),
                            })
                            .describe("A component's grid-size contract, in grid units.")
                            .describe('Grid-size contract for placements of this component.'),
                        configSchema: zod
                            .record(zod.string(), zod.unknown())
                            .optional()
                            .describe(
                                'JSON Schema (\"type\": \"object\") for a placement\'s config. The host validates each placement\'s config against it and passes the validated object to the widget at mount.'
                            ),
                    })
                    .describe("A component's placement contract: how grid canvases may place and configure it.")
                    .optional()
                    .describe(
                        'Placement contract, required for (and only allowed on) component-kind canvases: the grid size the component takes and the JSON Schema of its per-placement config.'
                    ),
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
                            state: zod
                                .array(zod.enum(['user', 'shared']).describe('\* `user` - user\n\* `shared` - shared'))
                                .max(canvasesValidateCreateBodyProjectOneCapabilitiesOnePosthogStateMax)
                                .optional()
                                .describe(
                                    "State scopes the canvas may use via ph.state: 'user' (private to each viewer) and\/or 'shared' (one value per canvas, team-visible)."
                                ),
                            actions: zod
                                .array(
                                    zod
                                        .string()
                                        .max(canvasesValidateCreateBodyProjectOneCapabilitiesOnePosthogActionsItemMax)
                                )
                                .max(canvasesValidateCreateBodyProjectOneCapabilitiesOnePosthogActionsMax)
                                .optional()
                                .describe(
                                    "Registered action verbs the canvas may invoke via ph.actions (e.g. 'annotations.create', 'tasks.create'). Each executes as the viewer; declaring one shows it in the promote review."
                                ),
                            agentRequests: zod
                                .boolean()
                                .default(
                                    canvasesValidateCreateBodyProjectOneCapabilitiesOnePosthogAgentRequestsDefault
                                ),
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
                        'Bounded capabilities frozen into the built artifact. Declare every insight short id the canvas loads, every event it captures, and inlineQueries when it runs ad-hoc HogQL — the host enforces these at runtime and validation rejects undeclared `ph` calls. Network origins must be exact HTTPS origins. Data fetched by canvas code can be sent to those origins.'
                    ),
            })
            .describe("A canvas's multi-file source project — the canonical write format for canvas source.")
            .describe('The candidate source project to validate.'),
    })
    .describe('Payload for validating a candidate source project without publishing it.')
