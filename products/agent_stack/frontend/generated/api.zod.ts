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
 * Agent applications — the deployable unit of the platform.

URLs:
    GET    /api/projects/<team>/agent_applications/             list
    POST   /api/projects/<team>/agent_applications/             create
    GET    /api/projects/<team>/agent_applications/<id|slug>/   retrieve
    PATCH  /api/projects/<team>/agent_applications/<id|slug>/   update
    DELETE /api/projects/<team>/agent_applications/<id|slug>/   archive
    POST   /api/projects/<team>/agent_applications/<id|slug>/set_env/        bulk replace env
    GET    /api/projects/<team>/agent_applications/<id|slug>/env_keys/        list set keys
    GET    /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  is one key set?
    PUT    /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  set one key
    DELETE /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  clear one key
 */
export const agentApplicationsCreateBodyNameMax = 255

export const agentApplicationsCreateBodySlugMax = 63

export const agentApplicationsCreateBodyArchivedDefault = false

export const AgentApplicationsCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(agentApplicationsCreateBodyNameMax),
    slug: zod.string().max(agentApplicationsCreateBodySlugMax),
    description: zod.string().optional(),
    archived: zod.boolean().default(agentApplicationsCreateBodyArchivedDefault),
})

/**
 * Create a memory file. Fails if the path already exists — use the update endpoint to overwrite.
 */
export const agentMemoryCreateFileBodyDescriptionMax = 280

export const AgentMemoryCreateFileBody = /* @__PURE__ */ zod
    .object({
        path: zod.string().describe('Where to store the file. Lowercase a-z 0-9 _ - \/ only, must end in .md.'),
        description: zod
            .string()
            .max(agentMemoryCreateFileBodyDescriptionMax)
            .describe('One-line summary, max 280 chars. Surfaces in list\/search results.'),
        content: zod.string().describe('Full markdown body.'),
        tags: zod
            .array(zod.string())
            .optional()
            .describe('Optional flat tags for search ranking. Lowercase a-z 0-9 _ - only.'),
    })
    .describe('Body shape for AgentMemoryViewSet.write_file (create).')

/**
 * Update a memory file. Any field omitted is preserved from the existing file.
 */
export const agentMemoryUpdateFileBodyDescriptionMax = 280

export const AgentMemoryUpdateFileBody = /* @__PURE__ */ zod
    .object({
        description: zod.string().max(agentMemoryUpdateFileBodyDescriptionMax).optional(),
        content: zod.string().optional(),
        tags: zod.array(zod.string()).optional(),
    })
    .describe('Body shape for AgentMemoryViewSet.update_file. Omitted fields preserve the existing value.')

/**
 * Revisions of an agent. Created in `draft`, promoted through
`ready → live` once the bundle has been uploaded + frozen.

URLs (nested under an application):

    Model CRUD:
        GET   .../revisions/                       list
        POST  .../revisions/                       create draft
        GET   .../revisions/<id>/                  retrieve
        PATCH .../revisions/<id>/                  update spec (draft only)

    Lifecycle:
        POST  .../revisions/<id>/promote/          ready → live
        POST  .../revisions/<id>/archive/          → archived
        POST  .../revisions/<id>/freeze/           draft → ready (stamps sha256)
        POST  .../revisions/<id>/clone_from/       copy bundle from another rev
        POST  .../revisions/new_draft/             create draft + clone_from atomically

    Bundle authoring (proxied to the janitor):
        GET    .../revisions/<id>/manifest/        list paths + sha256
        GET    .../revisions/<id>/file/?path=…     read one file
        PUT    .../revisions/<id>/file/?path=…     write one file (draft)
        DELETE .../revisions/<id>/file/?path=…     delete one file (draft)
        GET    .../revisions/<id>/bundle/          bulk pull all files
        PUT    .../revisions/<id>/bundle/          bulk push (replace|merge)
 */
export const agentApplicationsRevisionsCreateBodyBundleUriDefault = ``
export const agentApplicationsRevisionsCreateBodySpecTriggersItemOneConfigMentionOnlyDefault = false
export const agentApplicationsRevisionsCreateBodySpecTriggersItemThreeConfigTimezoneDefault = `UTC`
export const agentApplicationsRevisionsCreateBodySpecTriggersItemFourConfigRequireAuthDefault = true
export const agentApplicationsRevisionsCreateBodySpecTriggersItemFiveConfigDefault = {}
export const agentApplicationsRevisionsCreateBodySpecTriggersDefault = []
export const agentApplicationsRevisionsCreateBodySpecToolsItemThreeVersionMin = 0

export const agentApplicationsRevisionsCreateBodySpecToolsItemFourArgsSchemaDefault = {}
export const agentApplicationsRevisionsCreateBodySpecToolsItemFourRequiredDefault = false
export const agentApplicationsRevisionsCreateBodySpecToolsItemFourTimeoutMsDefault = 5000
export const agentApplicationsRevisionsCreateBodySpecToolsItemFourTimeoutMsMax = 60000

export const agentApplicationsRevisionsCreateBodySpecToolsDefault = []
export const agentApplicationsRevisionsCreateBodySpecMcpsDefault = []
export const agentApplicationsRevisionsCreateBodySpecSkillsItemVersionMin = 0

export const agentApplicationsRevisionsCreateBodySpecSkillsDefault = []
export const agentApplicationsRevisionsCreateBodySpecIntegrationsDefault = []
export const agentApplicationsRevisionsCreateBodySpecSecretsDefault = []
export const agentApplicationsRevisionsCreateBodySpecLimitsMaxTurnsDefault = 50
export const agentApplicationsRevisionsCreateBodySpecLimitsMaxTurnsExclusiveMin = 0
export const agentApplicationsRevisionsCreateBodySpecLimitsMaxTurnsMax = 2147483647

export const agentApplicationsRevisionsCreateBodySpecLimitsMaxToolCallsDefault = 200
export const agentApplicationsRevisionsCreateBodySpecLimitsMaxToolCallsExclusiveMin = 0
export const agentApplicationsRevisionsCreateBodySpecLimitsMaxToolCallsMax = 2147483647

export const agentApplicationsRevisionsCreateBodySpecLimitsMaxWallSecondsDefault = 900
export const agentApplicationsRevisionsCreateBodySpecLimitsMaxWallSecondsExclusiveMin = 0
export const agentApplicationsRevisionsCreateBodySpecLimitsMaxWallSecondsMax = 2147483647

export const agentApplicationsRevisionsCreateBodySpecLimitsDefault = {
    max_turns: 50,
    max_tool_calls: 200,
    max_wall_seconds: 900,
}
export const agentApplicationsRevisionsCreateBodySpecEntrypointDefault = `agent.md`
export const agentApplicationsRevisionsCreateBodySpecAuthModesItemTwoScopesDefault = []

export const agentApplicationsRevisionsCreateBodySpecAuthModesDefault = [{ type: `public` }]

export const AgentApplicationsRevisionsCreateBody = /* @__PURE__ */ zod.object({
    parent_revision: zod.uuid().nullish(),
    bundle_uri: zod.string().default(agentApplicationsRevisionsCreateBodyBundleUriDefault),
    spec: zod
        .object({
            model: zod.string().min(1),
            triggers: zod
                .array(
                    zod.union([
                        zod.object({
                            type: zod.literal('slack'),
                            config: zod.object({
                                channel_id: zod.string().optional(),
                                mention_only: zod
                                    .boolean()
                                    .default(
                                        agentApplicationsRevisionsCreateBodySpecTriggersItemOneConfigMentionOnlyDefault
                                    ),
                                trusted_workspaces: zod.union([zod.array(zod.string()).min(1), zod.literal('*')]),
                            }),
                        }),
                        zod.object({
                            type: zod.literal('webhook'),
                            config: zod.object({
                                path: zod.string(),
                                secret: zod.string().optional(),
                            }),
                        }),
                        zod.object({
                            type: zod.literal('cron'),
                            config: zod.object({
                                schedule: zod.string(),
                                timezone: zod
                                    .string()
                                    .default(
                                        agentApplicationsRevisionsCreateBodySpecTriggersItemThreeConfigTimezoneDefault
                                    ),
                            }),
                        }),
                        zod.object({
                            type: zod.literal('chat'),
                            config: zod.object({
                                require_auth: zod
                                    .boolean()
                                    .default(
                                        agentApplicationsRevisionsCreateBodySpecTriggersItemFourConfigRequireAuthDefault
                                    ),
                            }),
                        }),
                        zod.object({
                            type: zod.literal('mcp'),
                            config: zod
                                .object({})
                                .default(agentApplicationsRevisionsCreateBodySpecTriggersItemFiveConfigDefault),
                        }),
                    ])
                )
                .default(agentApplicationsRevisionsCreateBodySpecTriggersDefault),
            tools: zod
                .array(
                    zod.union([
                        zod.object({
                            kind: zod.literal('native'),
                            id: zod.string(),
                        }),
                        zod.object({
                            kind: zod.literal('custom'),
                            id: zod.string(),
                            path: zod.string(),
                        }),
                        zod.object({
                            kind: zod.literal('custom_template'),
                            from_template: zod.string(),
                            alias: zod.string(),
                            version: zod
                                .number()
                                .min(agentApplicationsRevisionsCreateBodySpecToolsItemThreeVersionMin)
                                .optional(),
                        }),
                        zod.object({
                            kind: zod.literal('client'),
                            id: zod.string().min(1),
                            description: zod.string().min(1),
                            args_schema: zod
                                .looseObject({})
                                .default(agentApplicationsRevisionsCreateBodySpecToolsItemFourArgsSchemaDefault),
                            required: zod
                                .boolean()
                                .default(agentApplicationsRevisionsCreateBodySpecToolsItemFourRequiredDefault),
                            timeout_ms: zod
                                .number()
                                .min(1)
                                .max(agentApplicationsRevisionsCreateBodySpecToolsItemFourTimeoutMsMax)
                                .default(agentApplicationsRevisionsCreateBodySpecToolsItemFourTimeoutMsDefault),
                        }),
                    ])
                )
                .default(agentApplicationsRevisionsCreateBodySpecToolsDefault),
            mcps: zod
                .array(
                    zod.union([
                        zod.object({
                            kind: zod.literal('agent'),
                            slug: zod.string(),
                        }),
                        zod.object({
                            kind: zod.literal('external'),
                            url: zod.url(),
                            auth: zod
                                .object({
                                    integration: zod.string().optional(),
                                })
                                .optional(),
                            allowlist: zod.array(zod.string()).optional(),
                        }),
                    ])
                )
                .default(agentApplicationsRevisionsCreateBodySpecMcpsDefault),
            skills: zod
                .array(
                    zod.object({
                        id: zod.string(),
                        path: zod.string(),
                        description: zod.string().optional(),
                        from_template: zod.string().optional(),
                        alias: zod.string().optional(),
                        version: zod
                            .number()
                            .min(agentApplicationsRevisionsCreateBodySpecSkillsItemVersionMin)
                            .optional(),
                    })
                )
                .default(agentApplicationsRevisionsCreateBodySpecSkillsDefault),
            integrations: zod.array(zod.string()).default(agentApplicationsRevisionsCreateBodySpecIntegrationsDefault),
            secrets: zod.array(zod.string()).default(agentApplicationsRevisionsCreateBodySpecSecretsDefault),
            limits: zod
                .object({
                    max_turns: zod
                        .number()
                        .gt(agentApplicationsRevisionsCreateBodySpecLimitsMaxTurnsExclusiveMin)
                        .max(agentApplicationsRevisionsCreateBodySpecLimitsMaxTurnsMax)
                        .default(agentApplicationsRevisionsCreateBodySpecLimitsMaxTurnsDefault),
                    max_tool_calls: zod
                        .number()
                        .gt(agentApplicationsRevisionsCreateBodySpecLimitsMaxToolCallsExclusiveMin)
                        .max(agentApplicationsRevisionsCreateBodySpecLimitsMaxToolCallsMax)
                        .default(agentApplicationsRevisionsCreateBodySpecLimitsMaxToolCallsDefault),
                    max_wall_seconds: zod
                        .number()
                        .gt(agentApplicationsRevisionsCreateBodySpecLimitsMaxWallSecondsExclusiveMin)
                        .max(agentApplicationsRevisionsCreateBodySpecLimitsMaxWallSecondsMax)
                        .default(agentApplicationsRevisionsCreateBodySpecLimitsMaxWallSecondsDefault),
                })
                .default(agentApplicationsRevisionsCreateBodySpecLimitsDefault),
            entrypoint: zod.string().default(agentApplicationsRevisionsCreateBodySpecEntrypointDefault),
            auth: zod.object({
                modes: zod
                    .array(
                        zod.union([
                            zod.object({
                                type: zod.literal('public'),
                            }),
                            zod.object({
                                type: zod.literal('oauth'),
                                issuer: zod.string().min(1),
                                scopes: zod
                                    .array(zod.string())
                                    .default(agentApplicationsRevisionsCreateBodySpecAuthModesItemTwoScopesDefault),
                            }),
                            zod.object({
                                type: zod.literal('pat'),
                            }),
                            zod.object({
                                type: zod.literal('jwt'),
                                issuer_secret_ref: zod.string().min(1),
                            }),
                            zod.object({
                                type: zod.literal('shared_secret'),
                                header: zod.string().min(1),
                            }),
                            zod.object({
                                type: zod.literal('posthog_internal'),
                            }),
                        ])
                    )
                    .default(agentApplicationsRevisionsCreateBodySpecAuthModesDefault),
            }),
            reasoning: zod.enum(['minimal', 'low', 'medium', 'high', 'xhigh']).optional(),
        })
        .optional(),
})

/**
 * Spec edits are only allowed while state='draft'. Once promoted to
ready/live the spec is frozen — change requires a new revision.
 */
export const agentApplicationsRevisionsUpdateBodyBundleUriDefault = ``
export const agentApplicationsRevisionsUpdateBodySpecTriggersItemOneConfigMentionOnlyDefault = false
export const agentApplicationsRevisionsUpdateBodySpecTriggersItemThreeConfigTimezoneDefault = `UTC`
export const agentApplicationsRevisionsUpdateBodySpecTriggersItemFourConfigRequireAuthDefault = true
export const agentApplicationsRevisionsUpdateBodySpecTriggersItemFiveConfigDefault = {}
export const agentApplicationsRevisionsUpdateBodySpecTriggersDefault = []
export const agentApplicationsRevisionsUpdateBodySpecToolsItemThreeVersionMin = 0

export const agentApplicationsRevisionsUpdateBodySpecToolsItemFourArgsSchemaDefault = {}
export const agentApplicationsRevisionsUpdateBodySpecToolsItemFourRequiredDefault = false
export const agentApplicationsRevisionsUpdateBodySpecToolsItemFourTimeoutMsDefault = 5000
export const agentApplicationsRevisionsUpdateBodySpecToolsItemFourTimeoutMsMax = 60000

export const agentApplicationsRevisionsUpdateBodySpecToolsDefault = []
export const agentApplicationsRevisionsUpdateBodySpecMcpsDefault = []
export const agentApplicationsRevisionsUpdateBodySpecSkillsItemVersionMin = 0

export const agentApplicationsRevisionsUpdateBodySpecSkillsDefault = []
export const agentApplicationsRevisionsUpdateBodySpecIntegrationsDefault = []
export const agentApplicationsRevisionsUpdateBodySpecSecretsDefault = []
export const agentApplicationsRevisionsUpdateBodySpecLimitsMaxTurnsDefault = 50
export const agentApplicationsRevisionsUpdateBodySpecLimitsMaxTurnsExclusiveMin = 0
export const agentApplicationsRevisionsUpdateBodySpecLimitsMaxTurnsMax = 2147483647

export const agentApplicationsRevisionsUpdateBodySpecLimitsMaxToolCallsDefault = 200
export const agentApplicationsRevisionsUpdateBodySpecLimitsMaxToolCallsExclusiveMin = 0
export const agentApplicationsRevisionsUpdateBodySpecLimitsMaxToolCallsMax = 2147483647

export const agentApplicationsRevisionsUpdateBodySpecLimitsMaxWallSecondsDefault = 900
export const agentApplicationsRevisionsUpdateBodySpecLimitsMaxWallSecondsExclusiveMin = 0
export const agentApplicationsRevisionsUpdateBodySpecLimitsMaxWallSecondsMax = 2147483647

export const agentApplicationsRevisionsUpdateBodySpecLimitsDefault = {
    max_turns: 50,
    max_tool_calls: 200,
    max_wall_seconds: 900,
}
export const agentApplicationsRevisionsUpdateBodySpecEntrypointDefault = `agent.md`
export const agentApplicationsRevisionsUpdateBodySpecAuthModesItemTwoScopesDefault = []

export const agentApplicationsRevisionsUpdateBodySpecAuthModesDefault = [{ type: `public` }]

export const AgentApplicationsRevisionsUpdateBody = /* @__PURE__ */ zod.object({
    parent_revision: zod.uuid().nullish(),
    bundle_uri: zod.string().default(agentApplicationsRevisionsUpdateBodyBundleUriDefault),
    spec: zod
        .object({
            model: zod.string().min(1),
            triggers: zod
                .array(
                    zod.union([
                        zod.object({
                            type: zod.literal('slack'),
                            config: zod.object({
                                channel_id: zod.string().optional(),
                                mention_only: zod
                                    .boolean()
                                    .default(
                                        agentApplicationsRevisionsUpdateBodySpecTriggersItemOneConfigMentionOnlyDefault
                                    ),
                                trusted_workspaces: zod.union([zod.array(zod.string()).min(1), zod.literal('*')]),
                            }),
                        }),
                        zod.object({
                            type: zod.literal('webhook'),
                            config: zod.object({
                                path: zod.string(),
                                secret: zod.string().optional(),
                            }),
                        }),
                        zod.object({
                            type: zod.literal('cron'),
                            config: zod.object({
                                schedule: zod.string(),
                                timezone: zod
                                    .string()
                                    .default(
                                        agentApplicationsRevisionsUpdateBodySpecTriggersItemThreeConfigTimezoneDefault
                                    ),
                            }),
                        }),
                        zod.object({
                            type: zod.literal('chat'),
                            config: zod.object({
                                require_auth: zod
                                    .boolean()
                                    .default(
                                        agentApplicationsRevisionsUpdateBodySpecTriggersItemFourConfigRequireAuthDefault
                                    ),
                            }),
                        }),
                        zod.object({
                            type: zod.literal('mcp'),
                            config: zod
                                .object({})
                                .default(agentApplicationsRevisionsUpdateBodySpecTriggersItemFiveConfigDefault),
                        }),
                    ])
                )
                .default(agentApplicationsRevisionsUpdateBodySpecTriggersDefault),
            tools: zod
                .array(
                    zod.union([
                        zod.object({
                            kind: zod.literal('native'),
                            id: zod.string(),
                        }),
                        zod.object({
                            kind: zod.literal('custom'),
                            id: zod.string(),
                            path: zod.string(),
                        }),
                        zod.object({
                            kind: zod.literal('custom_template'),
                            from_template: zod.string(),
                            alias: zod.string(),
                            version: zod
                                .number()
                                .min(agentApplicationsRevisionsUpdateBodySpecToolsItemThreeVersionMin)
                                .optional(),
                        }),
                        zod.object({
                            kind: zod.literal('client'),
                            id: zod.string().min(1),
                            description: zod.string().min(1),
                            args_schema: zod
                                .looseObject({})
                                .default(agentApplicationsRevisionsUpdateBodySpecToolsItemFourArgsSchemaDefault),
                            required: zod
                                .boolean()
                                .default(agentApplicationsRevisionsUpdateBodySpecToolsItemFourRequiredDefault),
                            timeout_ms: zod
                                .number()
                                .min(1)
                                .max(agentApplicationsRevisionsUpdateBodySpecToolsItemFourTimeoutMsMax)
                                .default(agentApplicationsRevisionsUpdateBodySpecToolsItemFourTimeoutMsDefault),
                        }),
                    ])
                )
                .default(agentApplicationsRevisionsUpdateBodySpecToolsDefault),
            mcps: zod
                .array(
                    zod.union([
                        zod.object({
                            kind: zod.literal('agent'),
                            slug: zod.string(),
                        }),
                        zod.object({
                            kind: zod.literal('external'),
                            url: zod.url(),
                            auth: zod
                                .object({
                                    integration: zod.string().optional(),
                                })
                                .optional(),
                            allowlist: zod.array(zod.string()).optional(),
                        }),
                    ])
                )
                .default(agentApplicationsRevisionsUpdateBodySpecMcpsDefault),
            skills: zod
                .array(
                    zod.object({
                        id: zod.string(),
                        path: zod.string(),
                        description: zod.string().optional(),
                        from_template: zod.string().optional(),
                        alias: zod.string().optional(),
                        version: zod
                            .number()
                            .min(agentApplicationsRevisionsUpdateBodySpecSkillsItemVersionMin)
                            .optional(),
                    })
                )
                .default(agentApplicationsRevisionsUpdateBodySpecSkillsDefault),
            integrations: zod.array(zod.string()).default(agentApplicationsRevisionsUpdateBodySpecIntegrationsDefault),
            secrets: zod.array(zod.string()).default(agentApplicationsRevisionsUpdateBodySpecSecretsDefault),
            limits: zod
                .object({
                    max_turns: zod
                        .number()
                        .gt(agentApplicationsRevisionsUpdateBodySpecLimitsMaxTurnsExclusiveMin)
                        .max(agentApplicationsRevisionsUpdateBodySpecLimitsMaxTurnsMax)
                        .default(agentApplicationsRevisionsUpdateBodySpecLimitsMaxTurnsDefault),
                    max_tool_calls: zod
                        .number()
                        .gt(agentApplicationsRevisionsUpdateBodySpecLimitsMaxToolCallsExclusiveMin)
                        .max(agentApplicationsRevisionsUpdateBodySpecLimitsMaxToolCallsMax)
                        .default(agentApplicationsRevisionsUpdateBodySpecLimitsMaxToolCallsDefault),
                    max_wall_seconds: zod
                        .number()
                        .gt(agentApplicationsRevisionsUpdateBodySpecLimitsMaxWallSecondsExclusiveMin)
                        .max(agentApplicationsRevisionsUpdateBodySpecLimitsMaxWallSecondsMax)
                        .default(agentApplicationsRevisionsUpdateBodySpecLimitsMaxWallSecondsDefault),
                })
                .default(agentApplicationsRevisionsUpdateBodySpecLimitsDefault),
            entrypoint: zod.string().default(agentApplicationsRevisionsUpdateBodySpecEntrypointDefault),
            auth: zod.object({
                modes: zod
                    .array(
                        zod.union([
                            zod.object({
                                type: zod.literal('public'),
                            }),
                            zod.object({
                                type: zod.literal('oauth'),
                                issuer: zod.string().min(1),
                                scopes: zod
                                    .array(zod.string())
                                    .default(agentApplicationsRevisionsUpdateBodySpecAuthModesItemTwoScopesDefault),
                            }),
                            zod.object({
                                type: zod.literal('pat'),
                            }),
                            zod.object({
                                type: zod.literal('jwt'),
                                issuer_secret_ref: zod.string().min(1),
                            }),
                            zod.object({
                                type: zod.literal('shared_secret'),
                                header: zod.string().min(1),
                            }),
                            zod.object({
                                type: zod.literal('posthog_internal'),
                            }),
                        ])
                    )
                    .default(agentApplicationsRevisionsUpdateBodySpecAuthModesDefault),
            }),
            reasoning: zod.enum(['minimal', 'low', 'medium', 'high', 'xhigh']).optional(),
        })
        .optional(),
})

/**
 * Revisions of an agent. Created in `draft`, promoted through
`ready → live` once the bundle has been uploaded + frozen.

URLs (nested under an application):

    Model CRUD:
        GET   .../revisions/                       list
        POST  .../revisions/                       create draft
        GET   .../revisions/<id>/                  retrieve
        PATCH .../revisions/<id>/                  update spec (draft only)

    Lifecycle:
        POST  .../revisions/<id>/promote/          ready → live
        POST  .../revisions/<id>/archive/          → archived
        POST  .../revisions/<id>/freeze/           draft → ready (stamps sha256)
        POST  .../revisions/<id>/clone_from/       copy bundle from another rev
        POST  .../revisions/new_draft/             create draft + clone_from atomically

    Bundle authoring (proxied to the janitor):
        GET    .../revisions/<id>/manifest/        list paths + sha256
        GET    .../revisions/<id>/file/?path=…     read one file
        PUT    .../revisions/<id>/file/?path=…     write one file (draft)
        DELETE .../revisions/<id>/file/?path=…     delete one file (draft)
        GET    .../revisions/<id>/bundle/          bulk pull all files
        PUT    .../revisions/<id>/bundle/          bulk push (replace|merge)
 */
export const agentApplicationsRevisionsPartialUpdateBodyBundleUriDefault = ``
export const agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemOneConfigMentionOnlyDefault = false
export const agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemThreeConfigTimezoneDefault = `UTC`
export const agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemFourConfigRequireAuthDefault = true
export const agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemFiveConfigDefault = {}
export const agentApplicationsRevisionsPartialUpdateBodySpecTriggersDefault = []
export const agentApplicationsRevisionsPartialUpdateBodySpecToolsItemThreeVersionMin = 0

export const agentApplicationsRevisionsPartialUpdateBodySpecToolsItemFourArgsSchemaDefault = {}
export const agentApplicationsRevisionsPartialUpdateBodySpecToolsItemFourRequiredDefault = false
export const agentApplicationsRevisionsPartialUpdateBodySpecToolsItemFourTimeoutMsDefault = 5000
export const agentApplicationsRevisionsPartialUpdateBodySpecToolsItemFourTimeoutMsMax = 60000

export const agentApplicationsRevisionsPartialUpdateBodySpecToolsDefault = []
export const agentApplicationsRevisionsPartialUpdateBodySpecMcpsDefault = []
export const agentApplicationsRevisionsPartialUpdateBodySpecSkillsItemVersionMin = 0

export const agentApplicationsRevisionsPartialUpdateBodySpecSkillsDefault = []
export const agentApplicationsRevisionsPartialUpdateBodySpecIntegrationsDefault = []
export const agentApplicationsRevisionsPartialUpdateBodySpecSecretsDefault = []
export const agentApplicationsRevisionsPartialUpdateBodySpecLimitsMaxTurnsDefault = 50
export const agentApplicationsRevisionsPartialUpdateBodySpecLimitsMaxTurnsExclusiveMin = 0
export const agentApplicationsRevisionsPartialUpdateBodySpecLimitsMaxTurnsMax = 2147483647

export const agentApplicationsRevisionsPartialUpdateBodySpecLimitsMaxToolCallsDefault = 200
export const agentApplicationsRevisionsPartialUpdateBodySpecLimitsMaxToolCallsExclusiveMin = 0
export const agentApplicationsRevisionsPartialUpdateBodySpecLimitsMaxToolCallsMax = 2147483647

export const agentApplicationsRevisionsPartialUpdateBodySpecLimitsMaxWallSecondsDefault = 900
export const agentApplicationsRevisionsPartialUpdateBodySpecLimitsMaxWallSecondsExclusiveMin = 0
export const agentApplicationsRevisionsPartialUpdateBodySpecLimitsMaxWallSecondsMax = 2147483647

export const agentApplicationsRevisionsPartialUpdateBodySpecLimitsDefault = {
    max_turns: 50,
    max_tool_calls: 200,
    max_wall_seconds: 900,
}
export const agentApplicationsRevisionsPartialUpdateBodySpecEntrypointDefault = `agent.md`
export const agentApplicationsRevisionsPartialUpdateBodySpecAuthModesItemTwoScopesDefault = []

export const agentApplicationsRevisionsPartialUpdateBodySpecAuthModesDefault = [{ type: `public` }]

export const AgentApplicationsRevisionsPartialUpdateBody = /* @__PURE__ */ zod.object({
    parent_revision: zod.uuid().nullish(),
    bundle_uri: zod.string().default(agentApplicationsRevisionsPartialUpdateBodyBundleUriDefault),
    spec: zod
        .object({
            model: zod.string().min(1),
            triggers: zod
                .array(
                    zod.union([
                        zod.object({
                            type: zod.literal('slack'),
                            config: zod.object({
                                channel_id: zod.string().optional(),
                                mention_only: zod
                                    .boolean()
                                    .default(
                                        agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemOneConfigMentionOnlyDefault
                                    ),
                                trusted_workspaces: zod.union([zod.array(zod.string()).min(1), zod.literal('*')]),
                            }),
                        }),
                        zod.object({
                            type: zod.literal('webhook'),
                            config: zod.object({
                                path: zod.string(),
                                secret: zod.string().optional(),
                            }),
                        }),
                        zod.object({
                            type: zod.literal('cron'),
                            config: zod.object({
                                schedule: zod.string(),
                                timezone: zod
                                    .string()
                                    .default(
                                        agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemThreeConfigTimezoneDefault
                                    ),
                            }),
                        }),
                        zod.object({
                            type: zod.literal('chat'),
                            config: zod.object({
                                require_auth: zod
                                    .boolean()
                                    .default(
                                        agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemFourConfigRequireAuthDefault
                                    ),
                            }),
                        }),
                        zod.object({
                            type: zod.literal('mcp'),
                            config: zod
                                .object({})
                                .default(agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemFiveConfigDefault),
                        }),
                    ])
                )
                .default(agentApplicationsRevisionsPartialUpdateBodySpecTriggersDefault),
            tools: zod
                .array(
                    zod.union([
                        zod.object({
                            kind: zod.literal('native'),
                            id: zod.string(),
                        }),
                        zod.object({
                            kind: zod.literal('custom'),
                            id: zod.string(),
                            path: zod.string(),
                        }),
                        zod.object({
                            kind: zod.literal('custom_template'),
                            from_template: zod.string(),
                            alias: zod.string(),
                            version: zod
                                .number()
                                .min(agentApplicationsRevisionsPartialUpdateBodySpecToolsItemThreeVersionMin)
                                .optional(),
                        }),
                        zod.object({
                            kind: zod.literal('client'),
                            id: zod.string().min(1),
                            description: zod.string().min(1),
                            args_schema: zod
                                .looseObject({})
                                .default(agentApplicationsRevisionsPartialUpdateBodySpecToolsItemFourArgsSchemaDefault),
                            required: zod
                                .boolean()
                                .default(agentApplicationsRevisionsPartialUpdateBodySpecToolsItemFourRequiredDefault),
                            timeout_ms: zod
                                .number()
                                .min(1)
                                .max(agentApplicationsRevisionsPartialUpdateBodySpecToolsItemFourTimeoutMsMax)
                                .default(agentApplicationsRevisionsPartialUpdateBodySpecToolsItemFourTimeoutMsDefault),
                        }),
                    ])
                )
                .default(agentApplicationsRevisionsPartialUpdateBodySpecToolsDefault),
            mcps: zod
                .array(
                    zod.union([
                        zod.object({
                            kind: zod.literal('agent'),
                            slug: zod.string(),
                        }),
                        zod.object({
                            kind: zod.literal('external'),
                            url: zod.url(),
                            auth: zod
                                .object({
                                    integration: zod.string().optional(),
                                })
                                .optional(),
                            allowlist: zod.array(zod.string()).optional(),
                        }),
                    ])
                )
                .default(agentApplicationsRevisionsPartialUpdateBodySpecMcpsDefault),
            skills: zod
                .array(
                    zod.object({
                        id: zod.string(),
                        path: zod.string(),
                        description: zod.string().optional(),
                        from_template: zod.string().optional(),
                        alias: zod.string().optional(),
                        version: zod
                            .number()
                            .min(agentApplicationsRevisionsPartialUpdateBodySpecSkillsItemVersionMin)
                            .optional(),
                    })
                )
                .default(agentApplicationsRevisionsPartialUpdateBodySpecSkillsDefault),
            integrations: zod
                .array(zod.string())
                .default(agentApplicationsRevisionsPartialUpdateBodySpecIntegrationsDefault),
            secrets: zod.array(zod.string()).default(agentApplicationsRevisionsPartialUpdateBodySpecSecretsDefault),
            limits: zod
                .object({
                    max_turns: zod
                        .number()
                        .gt(agentApplicationsRevisionsPartialUpdateBodySpecLimitsMaxTurnsExclusiveMin)
                        .max(agentApplicationsRevisionsPartialUpdateBodySpecLimitsMaxTurnsMax)
                        .default(agentApplicationsRevisionsPartialUpdateBodySpecLimitsMaxTurnsDefault),
                    max_tool_calls: zod
                        .number()
                        .gt(agentApplicationsRevisionsPartialUpdateBodySpecLimitsMaxToolCallsExclusiveMin)
                        .max(agentApplicationsRevisionsPartialUpdateBodySpecLimitsMaxToolCallsMax)
                        .default(agentApplicationsRevisionsPartialUpdateBodySpecLimitsMaxToolCallsDefault),
                    max_wall_seconds: zod
                        .number()
                        .gt(agentApplicationsRevisionsPartialUpdateBodySpecLimitsMaxWallSecondsExclusiveMin)
                        .max(agentApplicationsRevisionsPartialUpdateBodySpecLimitsMaxWallSecondsMax)
                        .default(agentApplicationsRevisionsPartialUpdateBodySpecLimitsMaxWallSecondsDefault),
                })
                .default(agentApplicationsRevisionsPartialUpdateBodySpecLimitsDefault),
            entrypoint: zod.string().default(agentApplicationsRevisionsPartialUpdateBodySpecEntrypointDefault),
            auth: zod.object({
                modes: zod
                    .array(
                        zod.union([
                            zod.object({
                                type: zod.literal('public'),
                            }),
                            zod.object({
                                type: zod.literal('oauth'),
                                issuer: zod.string().min(1),
                                scopes: zod
                                    .array(zod.string())
                                    .default(
                                        agentApplicationsRevisionsPartialUpdateBodySpecAuthModesItemTwoScopesDefault
                                    ),
                            }),
                            zod.object({
                                type: zod.literal('pat'),
                            }),
                            zod.object({
                                type: zod.literal('jwt'),
                                issuer_secret_ref: zod.string().min(1),
                            }),
                            zod.object({
                                type: zod.literal('shared_secret'),
                                header: zod.string().min(1),
                            }),
                            zod.object({
                                type: zod.literal('posthog_internal'),
                            }),
                        ])
                    )
                    .default(agentApplicationsRevisionsPartialUpdateBodySpecAuthModesDefault),
            }),
            reasoning: zod.enum(['minimal', 'low', 'medium', 'high', 'xhigh']).optional(),
        })
        .optional(),
})

/**
 * Bulk-push the bundle. Body `{ files, mode: replace|merge }`.
 */
export const agentApplicationsRevisionsBundleUpdateBodyModeDefault = `replace`

export const AgentApplicationsRevisionsBundleUpdateBody = /* @__PURE__ */ zod
    .object({
        files: zod.record(zod.string(), zod.string()),
        mode: zod
            .enum(['replace', 'merge'])
            .describe('\* `replace` - replace\n\* `merge` - merge')
            .default(agentApplicationsRevisionsBundleUpdateBodyModeDefault),
    })
    .describe(
        "Body shape for PUT \/revisions\/<id>\/bundle\/ — the bulk upload.\n\n`files` is a `{path: utf-8 content}` map. `mode='replace'` wipes the\nexisting bundle before writing the new set; `'merge'` upserts."
    )

/**
 * Copy every file from `source_revision_id` into this revision.
 */
export const AgentApplicationsRevisionsCloneFromCreateBody = /* @__PURE__ */ zod
    .object({
        source_revision_id: zod.uuid(),
    })
    .describe(
        'Body shape for POST \/revisions\/<id>\/clone_from\/ — copy every file\nfrom `source_revision_id` into this (draft) revision.'
    )

/**
 * Write one file by `?path=...`. Draft-only (janitor enforces).
 */
export const AgentApplicationsRevisionsFileUpdateBody = /* @__PURE__ */ zod
    .object({
        content: zod.string(),
    })
    .describe(
        'Body shape for PUT \/revisions\/<id>\/file\/. `path` lives in the query\nstring (matches the janitor wire format); `content` is the new file body.'
    )

/**
 * Create a fresh draft revision under `application_id` and seed it
from `source_revision_id`. Saves the MCP one round-trip vs the
explicit create + clone_from sequence.
 */
export const AgentApplicationsRevisionsNewDraftCreateBody = /* @__PURE__ */ zod
    .object({
        application_id: zod.uuid(),
        source_revision_id: zod.uuid(),
    })
    .describe(
        'Body shape for POST \/revisions\/clone_from\/ — atomically create a new\ndraft revision under `application_id` and clone its initial bundle from\n`source_revision_id`. Convenience for the \"edit live\" flow so the MCP\ndoesn\'t have to do create-then-clone-from in two calls.'
    )

/**
 * Agent applications — the deployable unit of the platform.

URLs:
    GET    /api/projects/<team>/agent_applications/             list
    POST   /api/projects/<team>/agent_applications/             create
    GET    /api/projects/<team>/agent_applications/<id|slug>/   retrieve
    PATCH  /api/projects/<team>/agent_applications/<id|slug>/   update
    DELETE /api/projects/<team>/agent_applications/<id|slug>/   archive
    POST   /api/projects/<team>/agent_applications/<id|slug>/set_env/        bulk replace env
    GET    /api/projects/<team>/agent_applications/<id|slug>/env_keys/        list set keys
    GET    /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  is one key set?
    PUT    /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  set one key
    DELETE /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  clear one key
 */
export const agentApplicationsUpdateBodyNameMax = 255

export const agentApplicationsUpdateBodySlugMax = 63

export const agentApplicationsUpdateBodyArchivedDefault = false

export const AgentApplicationsUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(agentApplicationsUpdateBodyNameMax),
    slug: zod.string().max(agentApplicationsUpdateBodySlugMax),
    description: zod.string().optional(),
    archived: zod.boolean().default(agentApplicationsUpdateBodyArchivedDefault),
})

/**
 * Agent applications — the deployable unit of the platform.

URLs:
    GET    /api/projects/<team>/agent_applications/             list
    POST   /api/projects/<team>/agent_applications/             create
    GET    /api/projects/<team>/agent_applications/<id|slug>/   retrieve
    PATCH  /api/projects/<team>/agent_applications/<id|slug>/   update
    DELETE /api/projects/<team>/agent_applications/<id|slug>/   archive
    POST   /api/projects/<team>/agent_applications/<id|slug>/set_env/        bulk replace env
    GET    /api/projects/<team>/agent_applications/<id|slug>/env_keys/        list set keys
    GET    /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  is one key set?
    PUT    /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  set one key
    DELETE /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  clear one key
 */
export const agentApplicationsPartialUpdateBodyNameMax = 255

export const agentApplicationsPartialUpdateBodySlugMax = 63

export const agentApplicationsPartialUpdateBodyArchivedDefault = false

export const AgentApplicationsPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(agentApplicationsPartialUpdateBodyNameMax).optional(),
    slug: zod.string().max(agentApplicationsPartialUpdateBodySlugMax).optional(),
    description: zod.string().optional(),
    archived: zod.boolean().default(agentApplicationsPartialUpdateBodyArchivedDefault),
})

/**
 * Approve or reject a queued tool-approval request. Team-admin only
(plan §6.1). The runtime side runs the tool platform-side on approve
and wakes the session with a synthetic tool_result either way.
 */
export const AgentApplicationsApprovalsDecideBody = /* @__PURE__ */ zod
    .object({
        decision: zod
            .enum(['approve', 'reject'])
            .describe('\* `approve` - approve\n\* `reject` - reject')
            .describe(
                "The approver's decision. `approve` runs the tool platform-side with the (possibly edited) args; `reject` records a terminal rejection and wakes the session with a synthetic rejected tool_result.\n\n\* `approve` - approve\n\* `reject` - reject"
            ),
        edited_args: zod
            .record(zod.string(), zod.unknown())
            .optional()
            .describe(
                "Approver-edited tool arguments. Only honoured when the tool's `approval_policy.allow_edit` is `true`; otherwise the janitor returns 422."
            ),
        reason: zod
            .string()
            .optional()
            .describe(
                "Free-form approver note. Surfaces in the session's synthetic tool_result so the model can communicate the reason back to the user."
            ),
    })
    .describe(
        'Body shape for POST \/agent_applications\/<id>\/approvals\/<approval_id>\/decide\/.\n\nSee docs\/agent-platform\/plans\/approval-gated-tools.md.'
    )

/**
 * GET / PUT / DELETE one secret by name.

- `GET`    → `{ key, is_set }` (never returns the value).
- `PUT`    → upserts `{ value }` into the env block.
- `DELETE` → removes the key. No-op when it wasn't set.

Per-method scope: GET is treated as a write action so the
single action name maps to one consistent scope; reading whether
a secret is set is restricted to writers in any case.
 */
export const AgentApplicationsEnvKeysSetBody = /* @__PURE__ */ zod
    .object({
        value: zod.string(),
    })
    .describe(
        'Body shape for AgentApplicationViewSet.env_keys_set — single secret upsert.\n\nThe view merges `{KEY: value}` into the existing encrypted env block\nwithout touching other keys, so callers can set or rotate one secret\nwithout needing to read the whole block back.'
    )

/**
 * Replace the agent's encrypted env block.

The body is `{ "env": { "<KEY>": "<value>", ... } }`. The encrypted
text gets stored on AgentApplication.encrypted_env; the worker
decrypts it at session start via the same Fernet schedule (see
agent-shared/src/runtime/encryption.ts).
 */
export const AgentApplicationsSetEnvCreateBody = /* @__PURE__ */ zod
    .object({
        env: zod.record(zod.string(), zod.string()),
    })
    .describe(
        'Body shape for AgentApplicationViewSet.set_env.\n\n`env` is a JSON object of string→string. The view encrypts it via the\nsame Fernet schedule the worker uses to decrypt.'
    )

/**
 * Shared, versioned TypeScript custom tool templates.

URLs:
    GET    /api/projects/<team>/agent_custom_tool_templates/
    POST   /api/projects/<team>/agent_custom_tool_templates/
    GET    /api/projects/<team>/agent_custom_tool_templates/name/<name>/
    POST   /api/projects/<team>/agent_custom_tool_templates/name/<name>/publish/
    POST   /api/projects/<team>/agent_custom_tool_templates/name/<name>/archive/
    POST   /api/projects/<team>/agent_custom_tool_templates/name/<name>/duplicate/
    GET    /api/projects/<team>/agent_custom_tool_templates/name/<name>/versions/
    GET    /api/projects/<team>/agent_custom_tool_templates/name/<name>/usages/
 * @summary Create a new custom tool template — produces v1.
 */
export const agentCustomToolTemplatesCreateBodyNameMax = 128

export const agentCustomToolTemplatesCreateBodyDescriptionDefault = ``
export const agentCustomToolTemplatesCreateBodyDescriptionMax = 4096

export const agentCustomToolTemplatesCreateBodySourceDefault = ``
export const agentCustomToolTemplatesCreateBodyCompiledJsDefault = ``
export const agentCustomToolTemplatesCreateBodyRequiresSecretsItemMax = 128

export const AgentCustomToolTemplatesCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(agentCustomToolTemplatesCreateBodyNameMax).describe('Slug-shaped name unique per team.'),
    description: zod
        .string()
        .max(agentCustomToolTemplatesCreateBodyDescriptionMax)
        .default(agentCustomToolTemplatesCreateBodyDescriptionDefault)
        .describe('One-line description.'),
    source: zod.string().default(agentCustomToolTemplatesCreateBodySourceDefault).describe('TypeScript source.'),
    compiled_js: zod
        .string()
        .default(agentCustomToolTemplatesCreateBodyCompiledJsDefault)
        .describe('Bundler output. The publisher (UI or MCP) computes this client-side.'),
    args_schema: zod.unknown().optional().describe('TypeBox \/ JSON Schema for tool args.'),
    returns_schema: zod.unknown().optional().describe('Optional TypeBox \/ JSON Schema for the return value.'),
    requires_secrets: zod
        .array(zod.string().max(agentCustomToolTemplatesCreateBodyRequiresSecretsItemMax))
        .optional()
        .describe('Names of secrets the tool reads via `ctx.secret(...)`.'),
})

/**
 * Shared, versioned TypeScript custom tool templates.

URLs:
    GET    /api/projects/<team>/agent_custom_tool_templates/
    POST   /api/projects/<team>/agent_custom_tool_templates/
    GET    /api/projects/<team>/agent_custom_tool_templates/name/<name>/
    POST   /api/projects/<team>/agent_custom_tool_templates/name/<name>/publish/
    POST   /api/projects/<team>/agent_custom_tool_templates/name/<name>/archive/
    POST   /api/projects/<team>/agent_custom_tool_templates/name/<name>/duplicate/
    GET    /api/projects/<team>/agent_custom_tool_templates/name/<name>/versions/
    GET    /api/projects/<team>/agent_custom_tool_templates/name/<name>/usages/
 * @summary Soft-delete all versions of a custom tool template.
 */
export const AgentCustomToolTemplatesNameArchiveCreateBody = /* @__PURE__ */ zod.object({
    source: zod.string().describe('TypeScript source the bundler compiles to `compiled_js`.'),
    compiled_js: zod
        .string()
        .describe('Last bundle output. Copied into `bundle\/tools\/<alias>\/compiled.js` at freeze.'),
    args_schema: zod.unknown().describe('TypeBox \/ JSON Schema for tool args.'),
    returns_schema: zod
        .unknown()
        .optional()
        .describe('Optional TypeBox \/ JSON Schema for the return value (informational).'),
})

/**
 * Shared, versioned TypeScript custom tool templates.

URLs:
    GET    /api/projects/<team>/agent_custom_tool_templates/
    POST   /api/projects/<team>/agent_custom_tool_templates/
    GET    /api/projects/<team>/agent_custom_tool_templates/name/<name>/
    POST   /api/projects/<team>/agent_custom_tool_templates/name/<name>/publish/
    POST   /api/projects/<team>/agent_custom_tool_templates/name/<name>/archive/
    POST   /api/projects/<team>/agent_custom_tool_templates/name/<name>/duplicate/
    GET    /api/projects/<team>/agent_custom_tool_templates/name/<name>/versions/
    GET    /api/projects/<team>/agent_custom_tool_templates/name/<name>/usages/
 * @summary Duplicate a custom tool template under a new name.
 */
export const agentCustomToolTemplatesNameDuplicateCreateBodyNameMax = 128

export const agentCustomToolTemplatesNameDuplicateCreateBodyDescriptionMax = 4096

export const AgentCustomToolTemplatesNameDuplicateCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(agentCustomToolTemplatesNameDuplicateCreateBodyNameMax).describe('Slug for the duplicate.'),
    description: zod
        .string()
        .max(agentCustomToolTemplatesNameDuplicateCreateBodyDescriptionMax)
        .optional()
        .describe('Description for the new template.'),
})

/**
 * Shared, versioned TypeScript custom tool templates.

URLs:
    GET    /api/projects/<team>/agent_custom_tool_templates/
    POST   /api/projects/<team>/agent_custom_tool_templates/
    GET    /api/projects/<team>/agent_custom_tool_templates/name/<name>/
    POST   /api/projects/<team>/agent_custom_tool_templates/name/<name>/publish/
    POST   /api/projects/<team>/agent_custom_tool_templates/name/<name>/archive/
    POST   /api/projects/<team>/agent_custom_tool_templates/name/<name>/duplicate/
    GET    /api/projects/<team>/agent_custom_tool_templates/name/<name>/versions/
    GET    /api/projects/<team>/agent_custom_tool_templates/name/<name>/usages/
 * @summary Publish a new version of the named custom tool template.
 */
export const agentCustomToolTemplatesNamePublishCreateBodyDescriptionMax = 4096

export const agentCustomToolTemplatesNamePublishCreateBodyRequiresSecretsItemMax = 128

export const AgentCustomToolTemplatesNamePublishCreateBody = /* @__PURE__ */ zod.object({
    description: zod
        .string()
        .max(agentCustomToolTemplatesNamePublishCreateBodyDescriptionMax)
        .optional()
        .describe('Overrides the prior description. Omit to keep the prior value.'),
    source: zod.string().optional().describe('Full new TypeScript source. Mutually exclusive with `edits`.'),
    edits: zod
        .array(
            zod
                .object({
                    old: zod.string().describe('Text to locate (must match exactly once).'),
                    new: zod.string().describe('Replacement text.'),
                })
                .describe('Structured edit applied to source.')
        )
        .optional()
        .describe('Structured edits against the current source.'),
    compiled_js: zod
        .string()
        .optional()
        .describe('Updated bundle output. Required when `source` or `edits` are supplied.'),
    args_schema: zod.unknown().optional().describe('Overrides args_schema. Omit to keep prior value.'),
    returns_schema: zod.unknown().optional().describe('Overrides returns_schema. Omit to keep prior value.'),
    requires_secrets: zod
        .array(zod.string().max(agentCustomToolTemplatesNamePublishCreateBodyRequiresSecretsItemMax))
        .optional()
        .describe('Overrides requires_secrets. Omit to keep prior value.'),
})

/**
 * Shared, versioned markdown skill templates.

URLs:
    GET    /api/projects/<team>/agent_skill_templates/
    POST   /api/projects/<team>/agent_skill_templates/
    GET    /api/projects/<team>/agent_skill_templates/name/<name>/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/publish/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/archive/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/duplicate/
    GET    /api/projects/<team>/agent_skill_templates/name/<name>/versions/
    GET    /api/projects/<team>/agent_skill_templates/name/<name>/usages/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/files/
    DELETE /api/projects/<team>/agent_skill_templates/name/<name>/files/<path>/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/files-rename/

Canonical (`@posthog/<name>`) templates are read-only for team
members; only PostHog-side seed commands write them.
 * @summary Create a new skill template — produces v1.
 */
export const agentSkillTemplatesCreateBodyNameMax = 64

export const agentSkillTemplatesCreateBodyDescriptionMax = 1024

export const agentSkillTemplatesCreateBodyBodyDefault = ``
export const agentSkillTemplatesCreateBodyLicenseDefault = ``
export const agentSkillTemplatesCreateBodyLicenseMax = 256

export const agentSkillTemplatesCreateBodyCompatibilityDefault = ``
export const agentSkillTemplatesCreateBodyCompatibilityMax = 500

export const agentSkillTemplatesCreateBodyFilesItemPathMax = 512

export const agentSkillTemplatesCreateBodyFilesItemContentTypeDefault = `text/plain`
export const agentSkillTemplatesCreateBodyFilesItemContentTypeMax = 128

export const AgentSkillTemplatesCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .max(agentSkillTemplatesCreateBodyNameMax)
            .describe(
                'Slug-shaped name unique per team (max 64 chars, per the Agent Skills spec). `@posthog\/<slug>` is reserved for canonical templates.'
            ),
        description: zod
            .string()
            .max(agentSkillTemplatesCreateBodyDescriptionMax)
            .describe(
                'Required description (1–1024 chars, per the Agent Skills spec) — what the skill does and when to use it. Shown in the list view + system-prompt skill index.'
            ),
        body: zod
            .string()
            .default(agentSkillTemplatesCreateBodyBodyDefault)
            .describe(
                'Initial SKILL.md markdown body. Any leading YAML frontmatter is stripped at freeze — frontmatter is assembled from the structured fields.'
            ),
        license: zod
            .string()
            .max(agentSkillTemplatesCreateBodyLicenseMax)
            .default(agentSkillTemplatesCreateBodyLicenseDefault)
            .describe('Agent Skills `license` frontmatter — license name or a reference to a bundled license file.'),
        compatibility: zod
            .string()
            .max(agentSkillTemplatesCreateBodyCompatibilityMax)
            .default(agentSkillTemplatesCreateBodyCompatibilityDefault)
            .describe(
                'Agent Skills `compatibility` frontmatter — environment requirements (intended product, packages, network access). Max 500 chars.'
            ),
        files: zod
            .array(
                zod.object({
                    id: zod.uuid(),
                    path: zod
                        .string()
                        .max(agentSkillTemplatesCreateBodyFilesItemPathMax)
                        .describe(
                            'Relative path inside the skill folder; may include subfolders (e.g. `references\/api.md`, `scripts\/run.py`, `assets\/x\/y.json`). Becomes `bundle\/skills\/<alias>\/<path>` at freeze. No `..` traversal or absolute paths.'
                        ),
                    content: zod
                        .string()
                        .describe(
                            'File body. Plain text or markdown — companion files are not interpreted by the runner.'
                        ),
                    content_type: zod
                        .string()
                        .max(agentSkillTemplatesCreateBodyFilesItemContentTypeMax)
                        .default(agentSkillTemplatesCreateBodyFilesItemContentTypeDefault)
                        .describe("MIME type hint. Read-only at runtime; aids the registry UI's file viewer."),
                })
            )
            .optional()
            .describe(
                'Optional companion files (scripts\/, references\/, assets\/ — arbitrarily nested) at creation time.'
            ),
        metadata: zod
            .unknown()
            .optional()
            .describe('Agent Skills `metadata` map (string → string) for non-promoted keys like author or version.'),
        allowed_tools: zod
            .unknown()
            .optional()
            .describe(
                "Optional list of tool ids the skill expects to reach for. Emitted as the spec's space-separated `allowed-tools` frontmatter at freeze."
            ),
    })
    .describe('Initial-create payload — produces v1.')

/**
 * Shared, versioned markdown skill templates.

URLs:
    GET    /api/projects/<team>/agent_skill_templates/
    POST   /api/projects/<team>/agent_skill_templates/
    GET    /api/projects/<team>/agent_skill_templates/name/<name>/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/publish/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/archive/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/duplicate/
    GET    /api/projects/<team>/agent_skill_templates/name/<name>/versions/
    GET    /api/projects/<team>/agent_skill_templates/name/<name>/usages/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/files/
    DELETE /api/projects/<team>/agent_skill_templates/name/<name>/files/<path>/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/files-rename/

Canonical (`@posthog/<name>`) templates are read-only for team
members; only PostHog-side seed commands write them.
 * @summary Soft-delete all versions of a template.
 */
export const AgentSkillTemplatesNameArchiveCreateBody = /* @__PURE__ */ zod
    .object({
        license: zod
            .string()
            .describe(
                'Agent Skills `license` frontmatter — license name or a reference to a bundled license file. Blank if unset.'
            ),
        compatibility: zod
            .string()
            .describe(
                'Agent Skills `compatibility` frontmatter — environment requirements (intended product, packages, network). Blank if unset.'
            ),
        body: zod.string().describe('Markdown body. The `SKILL.md` equivalent.'),
    })
    .describe('Detail shape: adds body + files. Used by the registry detail page.')

/**
 * Shared, versioned markdown skill templates.

URLs:
    GET    /api/projects/<team>/agent_skill_templates/
    POST   /api/projects/<team>/agent_skill_templates/
    GET    /api/projects/<team>/agent_skill_templates/name/<name>/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/publish/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/archive/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/duplicate/
    GET    /api/projects/<team>/agent_skill_templates/name/<name>/versions/
    GET    /api/projects/<team>/agent_skill_templates/name/<name>/usages/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/files/
    DELETE /api/projects/<team>/agent_skill_templates/name/<name>/files/<path>/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/files-rename/

Canonical (`@posthog/<name>`) templates are read-only for team
members; only PostHog-side seed commands write them.
 * @summary Duplicate a template under a new name (clones the latest version's content + files).
 */
export const agentSkillTemplatesNameDuplicateCreateBodyNameMax = 64

export const agentSkillTemplatesNameDuplicateCreateBodyDescriptionMax = 1024

export const AgentSkillTemplatesNameDuplicateCreateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(agentSkillTemplatesNameDuplicateCreateBodyNameMax)
        .describe('Slug for the new duplicate (max 64 chars). Must not collide with an existing template.'),
    description: zod
        .string()
        .max(agentSkillTemplatesNameDuplicateCreateBodyDescriptionMax)
        .optional()
        .describe("Description for the new template (1–1024 chars, non-empty). Omit to keep the source's description."),
})

/**
 * Shared, versioned markdown skill templates.

URLs:
    GET    /api/projects/<team>/agent_skill_templates/
    POST   /api/projects/<team>/agent_skill_templates/
    GET    /api/projects/<team>/agent_skill_templates/name/<name>/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/publish/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/archive/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/duplicate/
    GET    /api/projects/<team>/agent_skill_templates/name/<name>/versions/
    GET    /api/projects/<team>/agent_skill_templates/name/<name>/usages/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/files/
    DELETE /api/projects/<team>/agent_skill_templates/name/<name>/files/<path>/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/files-rename/

Canonical (`@posthog/<name>`) templates are read-only for team
members; only PostHog-side seed commands write them.
 * @summary Add a companion file to the latest version of the template.
 */
export const agentSkillTemplatesNameFilesCreateBodyPathMax = 512

export const agentSkillTemplatesNameFilesCreateBodyContentTypeDefault = `text/plain`
export const agentSkillTemplatesNameFilesCreateBodyContentTypeMax = 128

export const AgentSkillTemplatesNameFilesCreateBody = /* @__PURE__ */ zod.object({
    path: zod
        .string()
        .max(agentSkillTemplatesNameFilesCreateBodyPathMax)
        .describe(
            'Relative path inside the skill folder; may include subfolders (e.g. `references\/api.md`, `scripts\/run.py`). No `..` traversal or absolute paths.'
        ),
    content: zod.string().describe('File body.'),
    content_type: zod
        .string()
        .max(agentSkillTemplatesNameFilesCreateBodyContentTypeMax)
        .default(agentSkillTemplatesNameFilesCreateBodyContentTypeDefault)
        .describe('MIME type hint.'),
})

/**
 * Shared, versioned markdown skill templates.

URLs:
    GET    /api/projects/<team>/agent_skill_templates/
    POST   /api/projects/<team>/agent_skill_templates/
    GET    /api/projects/<team>/agent_skill_templates/name/<name>/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/publish/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/archive/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/duplicate/
    GET    /api/projects/<team>/agent_skill_templates/name/<name>/versions/
    GET    /api/projects/<team>/agent_skill_templates/name/<name>/usages/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/files/
    DELETE /api/projects/<team>/agent_skill_templates/name/<name>/files/<path>/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/files-rename/

Canonical (`@posthog/<name>`) templates are read-only for team
members; only PostHog-side seed commands write them.
 * @summary Rename a companion file inside the latest version of the template.
 */
export const agentSkillTemplatesNameFilesRenameCreateBodyFromPathMax = 512

export const agentSkillTemplatesNameFilesRenameCreateBodyToPathMax = 512

export const AgentSkillTemplatesNameFilesRenameCreateBody = /* @__PURE__ */ zod.object({
    from_path: zod
        .string()
        .max(agentSkillTemplatesNameFilesRenameCreateBodyFromPathMax)
        .describe('Existing file path inside the skill folder (subfolders allowed).'),
    to_path: zod
        .string()
        .max(agentSkillTemplatesNameFilesRenameCreateBodyToPathMax)
        .describe(
            'New path (subfolders allowed); may move the file between subfolders. Must not collide with another file.'
        ),
})

/**
 * Shared, versioned markdown skill templates.

URLs:
    GET    /api/projects/<team>/agent_skill_templates/
    POST   /api/projects/<team>/agent_skill_templates/
    GET    /api/projects/<team>/agent_skill_templates/name/<name>/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/publish/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/archive/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/duplicate/
    GET    /api/projects/<team>/agent_skill_templates/name/<name>/versions/
    GET    /api/projects/<team>/agent_skill_templates/name/<name>/usages/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/files/
    DELETE /api/projects/<team>/agent_skill_templates/name/<name>/files/<path>/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/files-rename/

Canonical (`@posthog/<name>`) templates are read-only for team
members; only PostHog-side seed commands write them.
 * @summary Publish a new version of the named template.
 */
export const agentSkillTemplatesNamePublishCreateBodyDescriptionMax = 1024

export const agentSkillTemplatesNamePublishCreateBodyLicenseMax = 256

export const agentSkillTemplatesNamePublishCreateBodyCompatibilityMax = 500

export const AgentSkillTemplatesNamePublishCreateBody = /* @__PURE__ */ zod
    .object({
        description: zod
            .string()
            .max(agentSkillTemplatesNamePublishCreateBodyDescriptionMax)
            .optional()
            .describe('Overrides the prior description (1–1024 chars, non-empty). Omit to keep the prior value.'),
        body: zod.string().optional().describe('Full new body. Mutually exclusive with `edits`.'),
        edits: zod
            .array(
                zod
                    .object({
                        old: zod.string().describe('Text to locate (must match exactly once).'),
                        new: zod.string().describe('Replacement text.'),
                        file_path: zod
                            .string()
                            .nullish()
                            .describe(
                                'Apply this edit to a companion file instead of the body. Null\/omitted = body edit.'
                            ),
                    })
                    .describe("A single find\/replace edit applied to body or a file's content.")
            )
            .optional()
            .describe('Structured edits. Each `old` must match exactly once in the current body \/ file.'),
        license: zod
            .string()
            .max(agentSkillTemplatesNamePublishCreateBodyLicenseMax)
            .optional()
            .describe('Overrides the `license` frontmatter. Omit to keep the prior value.'),
        compatibility: zod
            .string()
            .max(agentSkillTemplatesNamePublishCreateBodyCompatibilityMax)
            .optional()
            .describe('Overrides the `compatibility` frontmatter (max 500 chars). Omit to keep the prior value.'),
        metadata: zod.unknown().optional().describe('Overrides the metadata map. Omit to keep the prior value.'),
        allowed_tools: zod.unknown().optional().describe('Overrides allowed_tools. Omit to keep the prior value.'),
    })
    .describe(
        'Publish a new version.\n\nSupply EITHER `body` (full overwrite) OR `edits` (structured\nfind\/replace). The viewset rejects requests carrying both.'
    )
