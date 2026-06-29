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
 *
 * URLs:
 *     GET    /api/projects/<team>/agent_applications/             list
 *     POST   /api/projects/<team>/agent_applications/             create
 *     GET    /api/projects/<team>/agent_applications/<id|slug>/   retrieve
 *     PATCH  /api/projects/<team>/agent_applications/<id|slug>/   update
 *     DELETE /api/projects/<team>/agent_applications/<id|slug>/   archive
 *     POST   /api/projects/<team>/agent_applications/<id|slug>/set_env/        bulk replace env
 *     GET    /api/projects/<team>/agent_applications/<id|slug>/env_keys/        list set keys
 *     GET    /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  is one key set?
 *     PUT    /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  set one key
 *     DELETE /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  clear one key
 */
export const agentApplicationsCreateBodyNameMax = 255

export const agentApplicationsCreateBodySlugMax = 63

export const agentApplicationsCreateBodySlugRegExp = new RegExp('^[-a-zA-Z0-9_]+$')

export const AgentApplicationsCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(agentApplicationsCreateBodyNameMax),
    slug: zod
        .string()
        .max(agentApplicationsCreateBodySlugMax)
        .regex(agentApplicationsCreateBodySlugRegExp)
        .optional()
        .describe(
            'Globally-unique URL identifier. Server-minted as an opaque random slug on create; only allowlisted first-party teams may set it explicitly. Slugs live in one global namespace (domain-mode ingress routing carries no team).'
        ),
    description: zod.string().optional(),
    archived: zod.boolean().optional(),
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
 * `ready → live` once the bundle has been uploaded + frozen.
 *
 * URLs (nested under an application):
 *
 *     Model CRUD:
 *         GET   .../revisions/                       list
 *         POST  .../revisions/                       create draft
 *         GET   .../revisions/<id>/                  retrieve
 *         PATCH .../revisions/<id>/                  update spec (draft only)
 *
 *     Lifecycle:
 *         POST  .../revisions/<id>/promote/          ready → live
 *         POST  .../revisions/<id>/archive/          → archived
 *         POST  .../revisions/<id>/freeze/           draft → ready (stamps sha256)
 *         POST  .../revisions/<id>/clone_from/       copy bundle from another rev
 *         POST  .../revisions/new_draft/             create draft + clone_from atomically
 *
 *     Bundle authoring (proxied to the janitor):
 *         GET    .../revisions/<id>/manifest/        list paths + sha256
 *         GET    .../revisions/<id>/file/?path=…     read one file
 *         PUT    .../revisions/<id>/file/?path=…     write one file (draft)
 *         DELETE .../revisions/<id>/file/?path=…     delete one file (draft)
 *         GET    .../revisions/<id>/bundle/          bulk pull all files
 *         PUT    .../revisions/<id>/bundle/          bulk push (replace|merge)
 */
export const agentApplicationsRevisionsCreateBodyBundleUriDefault = ``
export const agentApplicationsRevisionsCreateBodySpecModelsOneLevelDefault = `medium`
export const agentApplicationsRevisionsCreateBodySpecModelsOneOptimizeForDefault = `cost`

export const agentApplicationsRevisionsCreateBodySpecModelsTwoModelsItemModelRegExp = new RegExp(
    '^[a-z0-9_-]+\/[a-zA-Z0-9._:-]+$'
)

export const agentApplicationsRevisionsCreateBodySpecModelsTwoOptimizeForDefault = `cost`
export const agentApplicationsRevisionsCreateBodySpecModelsDefault = {
    mode: 'auto' as const,
    level: 'medium' as const,
    optimize_for: 'cost' as const,
}
export const agentApplicationsRevisionsCreateBodySpecTriggersItemOneConfigMentionOnlyDefault = false
export const agentApplicationsRevisionsCreateBodySpecTriggersItemOneConfigAutoResumeThreadsDefault = false
export const agentApplicationsRevisionsCreateBodySpecTriggersItemOneConfigAllowWorkspaceParticipantsDefault = false
export const agentApplicationsRevisionsCreateBodySpecTriggersItemOneConfigAllowDirectMessagesDefault = false
export const agentApplicationsRevisionsCreateBodySpecTriggersItemTwoAuthModesItemTwoScopesDefault = []
export const agentApplicationsRevisionsCreateBodySpecTriggersItemTwoAuthModesItemTwoAudienceDefault = `project`

export const agentApplicationsRevisionsCreateBodySpecTriggersItemThreeConfigTimezoneDefault = `UTC`
export const agentApplicationsRevisionsCreateBodySpecTriggersItemThreeConfigPromptMax = 4096

export const agentApplicationsRevisionsCreateBodySpecTriggersItemThreeConfigCatchUpDefault = `most_recent`
export const agentApplicationsRevisionsCreateBodySpecTriggersItemThreeConfigMaxCatchUpAgeSecondsDefault = 3600
export const agentApplicationsRevisionsCreateBodySpecTriggersItemThreeConfigMaxCatchUpAgeSecondsMax = 604800

export const agentApplicationsRevisionsCreateBodySpecTriggersItemFourConfigAllowRestartDefault = false
export const agentApplicationsRevisionsCreateBodySpecTriggersItemFourConfigDefault = { allow_restart: false }
export const agentApplicationsRevisionsCreateBodySpecTriggersItemFourAuthModesItemTwoScopesDefault = []
export const agentApplicationsRevisionsCreateBodySpecTriggersItemFourAuthModesItemTwoAudienceDefault = `project`

export const agentApplicationsRevisionsCreateBodySpecTriggersItemFiveConfigAllowRestartDefault = false
export const agentApplicationsRevisionsCreateBodySpecTriggersItemFiveConfigDefault = { allow_restart: false }
export const agentApplicationsRevisionsCreateBodySpecTriggersItemFiveAuthModesItemTwoScopesDefault = []
export const agentApplicationsRevisionsCreateBodySpecTriggersItemFiveAuthModesItemTwoAudienceDefault = `project`

export const agentApplicationsRevisionsCreateBodySpecTriggersDefault = []
export const agentApplicationsRevisionsCreateBodySpecToolsItemOneRequiresApprovalDefault = false
export const agentApplicationsRevisionsCreateBodySpecToolsItemOneApprovalPolicyTypeDefault = `principal`
export const agentApplicationsRevisionsCreateBodySpecToolsItemOneApprovalPolicyAllowEditDefault = false
export const agentApplicationsRevisionsCreateBodySpecToolsItemOneApprovalPolicyTtlMsDefault = 86400000
export const agentApplicationsRevisionsCreateBodySpecToolsItemOneApprovalPolicyTtlMsMin = 60000
export const agentApplicationsRevisionsCreateBodySpecToolsItemOneApprovalPolicyTtlMsMax = 604800000

export const agentApplicationsRevisionsCreateBodySpecToolsItemTwoRequiresApprovalDefault = false
export const agentApplicationsRevisionsCreateBodySpecToolsItemTwoApprovalPolicyTypeDefault = `principal`
export const agentApplicationsRevisionsCreateBodySpecToolsItemTwoApprovalPolicyAllowEditDefault = false
export const agentApplicationsRevisionsCreateBodySpecToolsItemTwoApprovalPolicyTtlMsDefault = 86400000
export const agentApplicationsRevisionsCreateBodySpecToolsItemTwoApprovalPolicyTtlMsMin = 60000
export const agentApplicationsRevisionsCreateBodySpecToolsItemTwoApprovalPolicyTtlMsMax = 604800000

export const agentApplicationsRevisionsCreateBodySpecToolsItemFourArgsSchemaDefault = {}
export const agentApplicationsRevisionsCreateBodySpecToolsItemFourRequiredDefault = false
export const agentApplicationsRevisionsCreateBodySpecToolsItemFourTimeoutMsDefault = 5000
export const agentApplicationsRevisionsCreateBodySpecToolsItemFourTimeoutMsMax = 600000

export const agentApplicationsRevisionsCreateBodySpecToolsItemFourInteractiveDefault = false
export const agentApplicationsRevisionsCreateBodySpecToolsDefault = []
export const agentApplicationsRevisionsCreateBodySpecMcpsItemSecretsDefault = []

export const agentApplicationsRevisionsCreateBodySpecMcpsItemToolsItemTwoRequiresApprovalDefault = false
export const agentApplicationsRevisionsCreateBodySpecMcpsItemToolsItemTwoApprovalPolicyTypeDefault = `principal`
export const agentApplicationsRevisionsCreateBodySpecMcpsItemToolsItemTwoApprovalPolicyAllowEditDefault = false
export const agentApplicationsRevisionsCreateBodySpecMcpsItemToolsItemTwoApprovalPolicyTtlMsDefault = 86400000
export const agentApplicationsRevisionsCreateBodySpecMcpsItemToolsItemTwoApprovalPolicyTtlMsMin = 60000
export const agentApplicationsRevisionsCreateBodySpecMcpsItemToolsItemTwoApprovalPolicyTtlMsMax = 604800000

export const agentApplicationsRevisionsCreateBodySpecMcpsDefault = []
export const agentApplicationsRevisionsCreateBodySpecSkillsDefault = []
export const agentApplicationsRevisionsCreateBodySpecIdentityProvidersItemOneIdDefault = `posthog`

export const agentApplicationsRevisionsCreateBodySpecIdentityProvidersItemOneBindingDefault = `principal`
export const agentApplicationsRevisionsCreateBodySpecIdentityProvidersItemOneScopesDefault = []
export const agentApplicationsRevisionsCreateBodySpecIdentityProvidersItemTwoBindingDefault = `principal`
export const agentApplicationsRevisionsCreateBodySpecIdentityProvidersItemTwoScopesDefault = []
export const agentApplicationsRevisionsCreateBodySpecIdentityProvidersDefault = []

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

export const agentApplicationsRevisionsCreateBodySpecLimitsMaxOutputTokensExclusiveMin = 0
export const agentApplicationsRevisionsCreateBodySpecLimitsMaxOutputTokensMax = 200000

export const agentApplicationsRevisionsCreateBodySpecLimitsMaxMemoryMbDefault = 512
export const agentApplicationsRevisionsCreateBodySpecLimitsMaxMemoryMbExclusiveMin = 0
export const agentApplicationsRevisionsCreateBodySpecLimitsMaxMemoryMbMax = 16384

export const agentApplicationsRevisionsCreateBodySpecLimitsMaxCpuCoresDefault = 0.25
export const agentApplicationsRevisionsCreateBodySpecLimitsMaxCpuCoresExclusiveMin = 0
export const agentApplicationsRevisionsCreateBodySpecLimitsMaxCpuCoresMax = 8

export const agentApplicationsRevisionsCreateBodySpecLimitsDefault = {
    max_turns: 50,
    max_tool_calls: 200,
    max_wall_seconds: 900,
    max_memory_mb: 512,
    max_cpu_cores: 0.25,
}
export const agentApplicationsRevisionsCreateBodySpecFrameworkPromptOmitDefault = []
export const agentApplicationsRevisionsCreateBodySpecFrameworkPromptVersionPinExclusiveMin = 0
export const agentApplicationsRevisionsCreateBodySpecFrameworkPromptVersionPinMax = 2147483647

export const agentApplicationsRevisionsCreateBodySpecResumeEnabledDefault = false
export const agentApplicationsRevisionsCreateBodySpecResumeMaxCompletedAgeMsDefault = 604800000
export const agentApplicationsRevisionsCreateBodySpecResumeMaxCompletedAgeMsExclusiveMin = 0
export const agentApplicationsRevisionsCreateBodySpecResumeMaxCompletedAgeMsMax = 2147483647

export const AgentApplicationsRevisionsCreateBody = /* @__PURE__ */ zod.object({
    parent_revision: zod.uuid().nullish(),
    bundle_uri: zod
        .string()
        .default(agentApplicationsRevisionsCreateBodyBundleUriDefault)
        .describe(
            'Storage-prefix metadata for the bundle, e.g. `fs:\/\/my-agent\/`. Optional — leave blank and the server fills `fs:\/\/<application-slug>\/`. Bundles are addressed by revision id regardless, so this is only a prefix hint.'
        ),
    spec: zod
        .object({
            models: zod
                .union([
                    zod.object({
                        mode: zod.literal('auto'),
                        level: zod
                            .enum(['low', 'medium', 'high'])
                            .default(agentApplicationsRevisionsCreateBodySpecModelsOneLevelDefault)
                            .describe(
                                'Quality\/cost tier (auto). low = cheapest, for short, formulaic, no-reasoning jobs (lookups, FAQ bots); medium = balanced default, for multi-step but bounded work; high = top-tier, for long, branching, reasoning-heavy work. Resolved to a priority-ordered cross-provider list at session start.'
                            ),
                        reasoning: zod
                            .enum(['minimal', 'low', 'medium', 'high', 'xhigh'])
                            .optional()
                            .describe(
                                'Reasoning\/thinking effort budget. minimal = no deliberation (fastest, cheapest) … xhigh = maximal (research-grade, ~5-10x the per-turn cost). Omit for the provider\/spec default.'
                            ),
                        optimize_for: zod
                            .enum(['cost', 'availability'])
                            .default(agentApplicationsRevisionsCreateBodySpecModelsOneOptimizeForDefault)
                            .describe(
                                "Session model stability vs. resilience. `cost` (default): the first turn picks a working model and PINS it for the whole session — keeps the provider's prompt cache warm (cache reads are ~0.1-0.5x of full input) and never fails over mid-session; if the pinned model is down the turn fails rather than re-reading the whole context cold on another provider. `availability`: fail over to the next model when the session's model fails — survives an outage at the cost of a one-time cold re-read. Prefer `cost` for long\/expensive sessions, `availability` where uptime matters more than spend."
                            ),
                    }),
                    zod.object({
                        mode: zod.literal('manual'),
                        models: zod
                            .array(
                                zod.object({
                                    model: zod
                                        .string()
                                        .min(1)
                                        .regex(agentApplicationsRevisionsCreateBodySpecModelsTwoModelsItemModelRegExp)
                                        .describe(
                                            'Canonical model id, e.g. `anthropic\/claude-sonnet-4-6` (see the agent-applications-models tool for served ids).'
                                        ),
                                    reasoning: zod
                                        .enum(['minimal', 'low', 'medium', 'high', 'xhigh'])
                                        .optional()
                                        .describe('Per-model reasoning effort override (else the spec default).'),
                                })
                            )
                            .min(1)
                            .describe(
                                'Explicit priority-ordered fallback list — the runner tries entries in order (primary first).'
                            ),
                        optimize_for: zod
                            .enum(['cost', 'availability'])
                            .default(agentApplicationsRevisionsCreateBodySpecModelsTwoOptimizeForDefault)
                            .describe(
                                "Session model stability vs. resilience. `cost` (default): pin the first working model for the whole session (warm prompt cache, no mid-session failover). `availability`: fail over down this list when the session's model fails (survives outages, re-reads context cold)."
                            ),
                    }),
                ])
                .default(agentApplicationsRevisionsCreateBodySpecModelsDefault)
                .describe(
                    "How this agent selects its model. `auto`: pick a quality\/cost `level` and the platform resolves it to a maintained, priority-ordered, cross-provider list at runtime. `manual`: give an explicit priority-ordered `models` list (primary first). `optimize_for` governs how the chosen model is treated across the session's turns."
                ),
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
                                auto_resume_threads: zod
                                    .boolean()
                                    .default(
                                        agentApplicationsRevisionsCreateBodySpecTriggersItemOneConfigAutoResumeThreadsDefault
                                    ),
                                allow_workspace_participants: zod
                                    .boolean()
                                    .default(
                                        agentApplicationsRevisionsCreateBodySpecTriggersItemOneConfigAllowWorkspaceParticipantsDefault
                                    ),
                                ack_reaction: zod.string().optional(),
                                allow_direct_messages: zod
                                    .boolean()
                                    .default(
                                        agentApplicationsRevisionsCreateBodySpecTriggersItemOneConfigAllowDirectMessagesDefault
                                    ),
                                trusted_workspaces: zod.union([zod.array(zod.string()).min(1), zod.literal('*')]),
                            }),
                        }),
                        zod.object({
                            type: zod.literal('webhook'),
                            config: zod.object({
                                path: zod.string(),
                            }),
                            auth: zod.object({
                                modes: zod
                                    .array(
                                        zod.union([
                                            zod.object({
                                                type: zod.literal('public'),
                                                acknowledge_public_exposure: zod.boolean(),
                                            }),
                                            zod.object({
                                                type: zod.literal('posthog'),
                                                scopes: zod
                                                    .array(zod.string())
                                                    .default(
                                                        agentApplicationsRevisionsCreateBodySpecTriggersItemTwoAuthModesItemTwoScopesDefault
                                                    ),
                                                audience: zod
                                                    .enum(['project', 'organization'])
                                                    .default(
                                                        agentApplicationsRevisionsCreateBodySpecTriggersItemTwoAuthModesItemTwoAudienceDefault
                                                    ),
                                            }),
                                            zod.object({
                                                type: zod.literal('jwt'),
                                                issuer_secret_ref: zod.string().min(1),
                                            }),
                                            zod.object({
                                                type: zod.literal('shared_secret'),
                                                header: zod.string().min(1),
                                                secret_ref: zod.string().min(1),
                                            }),
                                            zod.object({
                                                type: zod.literal('posthog_internal'),
                                            }),
                                        ])
                                    )
                                    .optional(),
                            }),
                        }),
                        zod.object({
                            type: zod.literal('cron'),
                            config: zod.object({
                                name: zod.string().min(1),
                                schedule: zod.string().min(1),
                                timezone: zod
                                    .string()
                                    .default(
                                        agentApplicationsRevisionsCreateBodySpecTriggersItemThreeConfigTimezoneDefault
                                    ),
                                prompt: zod
                                    .string()
                                    .min(1)
                                    .max(agentApplicationsRevisionsCreateBodySpecTriggersItemThreeConfigPromptMax),
                                external_key: zod.string().optional(),
                                catch_up: zod
                                    .enum(['all', 'most_recent', 'skip'])
                                    .default(
                                        agentApplicationsRevisionsCreateBodySpecTriggersItemThreeConfigCatchUpDefault
                                    ),
                                max_catch_up_age_seconds: zod
                                    .number()
                                    .min(1)
                                    .max(
                                        agentApplicationsRevisionsCreateBodySpecTriggersItemThreeConfigMaxCatchUpAgeSecondsMax
                                    )
                                    .default(
                                        agentApplicationsRevisionsCreateBodySpecTriggersItemThreeConfigMaxCatchUpAgeSecondsDefault
                                    ),
                            }),
                        }),
                        zod.object({
                            type: zod.literal('chat'),
                            config: zod
                                .object({
                                    allow_restart: zod
                                        .boolean()
                                        .default(
                                            agentApplicationsRevisionsCreateBodySpecTriggersItemFourConfigAllowRestartDefault
                                        ),
                                })
                                .default(agentApplicationsRevisionsCreateBodySpecTriggersItemFourConfigDefault),
                            auth: zod.object({
                                modes: zod
                                    .array(
                                        zod.union([
                                            zod.object({
                                                type: zod.literal('public'),
                                                acknowledge_public_exposure: zod.boolean(),
                                            }),
                                            zod.object({
                                                type: zod.literal('posthog'),
                                                scopes: zod
                                                    .array(zod.string())
                                                    .default(
                                                        agentApplicationsRevisionsCreateBodySpecTriggersItemFourAuthModesItemTwoScopesDefault
                                                    ),
                                                audience: zod
                                                    .enum(['project', 'organization'])
                                                    .default(
                                                        agentApplicationsRevisionsCreateBodySpecTriggersItemFourAuthModesItemTwoAudienceDefault
                                                    ),
                                            }),
                                            zod.object({
                                                type: zod.literal('jwt'),
                                                issuer_secret_ref: zod.string().min(1),
                                            }),
                                            zod.object({
                                                type: zod.literal('shared_secret'),
                                                header: zod.string().min(1),
                                                secret_ref: zod.string().min(1),
                                            }),
                                            zod.object({
                                                type: zod.literal('posthog_internal'),
                                            }),
                                        ])
                                    )
                                    .optional(),
                            }),
                        }),
                        zod.object({
                            type: zod.literal('mcp'),
                            config: zod
                                .object({
                                    allow_restart: zod
                                        .boolean()
                                        .default(
                                            agentApplicationsRevisionsCreateBodySpecTriggersItemFiveConfigAllowRestartDefault
                                        ),
                                })
                                .default(agentApplicationsRevisionsCreateBodySpecTriggersItemFiveConfigDefault),
                            auth: zod.object({
                                modes: zod
                                    .array(
                                        zod.union([
                                            zod.object({
                                                type: zod.literal('public'),
                                                acknowledge_public_exposure: zod.boolean(),
                                            }),
                                            zod.object({
                                                type: zod.literal('posthog'),
                                                scopes: zod
                                                    .array(zod.string())
                                                    .default(
                                                        agentApplicationsRevisionsCreateBodySpecTriggersItemFiveAuthModesItemTwoScopesDefault
                                                    ),
                                                audience: zod
                                                    .enum(['project', 'organization'])
                                                    .default(
                                                        agentApplicationsRevisionsCreateBodySpecTriggersItemFiveAuthModesItemTwoAudienceDefault
                                                    ),
                                            }),
                                            zod.object({
                                                type: zod.literal('jwt'),
                                                issuer_secret_ref: zod.string().min(1),
                                            }),
                                            zod.object({
                                                type: zod.literal('shared_secret'),
                                                header: zod.string().min(1),
                                                secret_ref: zod.string().min(1),
                                            }),
                                            zod.object({
                                                type: zod.literal('posthog_internal'),
                                            }),
                                        ])
                                    )
                                    .optional(),
                            }),
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
                            requires_approval: zod
                                .boolean()
                                .default(agentApplicationsRevisionsCreateBodySpecToolsItemOneRequiresApprovalDefault),
                            approval_policy: zod
                                .object({
                                    type: zod
                                        .enum(['principal', 'agent'])
                                        .default(
                                            agentApplicationsRevisionsCreateBodySpecToolsItemOneApprovalPolicyTypeDefault
                                        ),
                                    allow_edit: zod
                                        .boolean()
                                        .default(
                                            agentApplicationsRevisionsCreateBodySpecToolsItemOneApprovalPolicyAllowEditDefault
                                        ),
                                    ttl_ms: zod
                                        .number()
                                        .min(agentApplicationsRevisionsCreateBodySpecToolsItemOneApprovalPolicyTtlMsMin)
                                        .max(agentApplicationsRevisionsCreateBodySpecToolsItemOneApprovalPolicyTtlMsMax)
                                        .default(
                                            agentApplicationsRevisionsCreateBodySpecToolsItemOneApprovalPolicyTtlMsDefault
                                        ),
                                })
                                .optional(),
                        }),
                        zod.object({
                            kind: zod.literal('custom'),
                            id: zod.string(),
                            path: zod.string(),
                            requires_approval: zod
                                .boolean()
                                .default(agentApplicationsRevisionsCreateBodySpecToolsItemTwoRequiresApprovalDefault),
                            approval_policy: zod
                                .object({
                                    type: zod
                                        .enum(['principal', 'agent'])
                                        .default(
                                            agentApplicationsRevisionsCreateBodySpecToolsItemTwoApprovalPolicyTypeDefault
                                        ),
                                    allow_edit: zod
                                        .boolean()
                                        .default(
                                            agentApplicationsRevisionsCreateBodySpecToolsItemTwoApprovalPolicyAllowEditDefault
                                        ),
                                    ttl_ms: zod
                                        .number()
                                        .min(agentApplicationsRevisionsCreateBodySpecToolsItemTwoApprovalPolicyTtlMsMin)
                                        .max(agentApplicationsRevisionsCreateBodySpecToolsItemTwoApprovalPolicyTtlMsMax)
                                        .default(
                                            agentApplicationsRevisionsCreateBodySpecToolsItemTwoApprovalPolicyTtlMsDefault
                                        ),
                                })
                                .optional(),
                            requires_identity: zod.string().optional(),
                        }),
                        zod.object({
                            kind: zod.literal('custom_template'),
                            from_template: zod.string(),
                            alias: zod.string(),
                            version: zod.number().min(1).optional(),
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
                            interactive: zod
                                .boolean()
                                .default(agentApplicationsRevisionsCreateBodySpecToolsItemFourInteractiveDefault),
                        }),
                    ])
                )
                .default(agentApplicationsRevisionsCreateBodySpecToolsDefault),
            mcps: zod
                .array(
                    zod.object({
                        id: zod.string().min(1),
                        url: zod.url(),
                        auth: zod
                            .object({
                                provider: zod.string().optional(),
                            })
                            .optional(),
                        secrets: zod
                            .array(zod.string())
                            .default(agentApplicationsRevisionsCreateBodySpecMcpsItemSecretsDefault),
                        headers: zod.record(zod.string(), zod.string()).optional(),
                        tools: zod
                            .array(
                                zod.union([
                                    zod.string().min(1),
                                    zod.object({
                                        name: zod.string().min(1),
                                        requires_approval: zod
                                            .boolean()
                                            .default(
                                                agentApplicationsRevisionsCreateBodySpecMcpsItemToolsItemTwoRequiresApprovalDefault
                                            ),
                                        approval_policy: zod
                                            .object({
                                                type: zod
                                                    .enum(['principal', 'agent'])
                                                    .default(
                                                        agentApplicationsRevisionsCreateBodySpecMcpsItemToolsItemTwoApprovalPolicyTypeDefault
                                                    ),
                                                allow_edit: zod
                                                    .boolean()
                                                    .default(
                                                        agentApplicationsRevisionsCreateBodySpecMcpsItemToolsItemTwoApprovalPolicyAllowEditDefault
                                                    ),
                                                ttl_ms: zod
                                                    .number()
                                                    .min(
                                                        agentApplicationsRevisionsCreateBodySpecMcpsItemToolsItemTwoApprovalPolicyTtlMsMin
                                                    )
                                                    .max(
                                                        agentApplicationsRevisionsCreateBodySpecMcpsItemToolsItemTwoApprovalPolicyTtlMsMax
                                                    )
                                                    .default(
                                                        agentApplicationsRevisionsCreateBodySpecMcpsItemToolsItemTwoApprovalPolicyTtlMsDefault
                                                    ),
                                            })
                                            .optional(),
                                    }),
                                ])
                            )
                            .optional(),
                    })
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
                        version: zod.number().min(1).optional(),
                        source_version_id: zod.string().optional(),
                    })
                )
                .default(agentApplicationsRevisionsCreateBodySpecSkillsDefault),
            identity_providers: zod
                .array(
                    zod.union([
                        zod.object({
                            kind: zod.literal('posthog'),
                            id: zod
                                .string()
                                .min(1)
                                .default(agentApplicationsRevisionsCreateBodySpecIdentityProvidersItemOneIdDefault),
                            binding: zod
                                .enum(['principal'])
                                .default(
                                    agentApplicationsRevisionsCreateBodySpecIdentityProvidersItemOneBindingDefault
                                ),
                            scopes: zod
                                .array(zod.string())
                                .default(agentApplicationsRevisionsCreateBodySpecIdentityProvidersItemOneScopesDefault),
                            client_id: zod.string().optional(),
                        }),
                        zod.object({
                            kind: zod.literal('oauth2'),
                            id: zod.string().min(1),
                            binding: zod
                                .enum(['principal'])
                                .default(
                                    agentApplicationsRevisionsCreateBodySpecIdentityProvidersItemTwoBindingDefault
                                ),
                            authorize_url: zod.url(),
                            token_url: zod.url(),
                            client_id: zod.string().min(1),
                            client_secret_ref: zod.string().optional(),
                            scopes: zod
                                .array(zod.string())
                                .default(agentApplicationsRevisionsCreateBodySpecIdentityProvidersItemTwoScopesDefault),
                            userinfo_url: zod.url().optional(),
                        }),
                    ])
                )
                .default(agentApplicationsRevisionsCreateBodySpecIdentityProvidersDefault),
            secrets: zod
                .array(
                    zod.union([
                        zod.string().min(1),
                        zod.object({
                            name: zod.string().min(1),
                            allowed_hosts: zod.array(zod.string().min(1)).min(1),
                        }),
                    ])
                )
                .default(agentApplicationsRevisionsCreateBodySpecSecretsDefault),
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
                    max_output_tokens: zod
                        .number()
                        .gt(agentApplicationsRevisionsCreateBodySpecLimitsMaxOutputTokensExclusiveMin)
                        .max(agentApplicationsRevisionsCreateBodySpecLimitsMaxOutputTokensMax)
                        .optional(),
                    max_memory_mb: zod
                        .number()
                        .gt(agentApplicationsRevisionsCreateBodySpecLimitsMaxMemoryMbExclusiveMin)
                        .max(agentApplicationsRevisionsCreateBodySpecLimitsMaxMemoryMbMax)
                        .default(agentApplicationsRevisionsCreateBodySpecLimitsMaxMemoryMbDefault),
                    max_cpu_cores: zod
                        .number()
                        .gt(agentApplicationsRevisionsCreateBodySpecLimitsMaxCpuCoresExclusiveMin)
                        .max(agentApplicationsRevisionsCreateBodySpecLimitsMaxCpuCoresMax)
                        .default(agentApplicationsRevisionsCreateBodySpecLimitsMaxCpuCoresDefault),
                })
                .default(agentApplicationsRevisionsCreateBodySpecLimitsDefault),
            reasoning: zod.enum(['minimal', 'low', 'medium', 'high', 'xhigh']).optional(),
            framework_prompt: zod
                .object({
                    omit: zod
                        .array(
                            zod.enum([
                                'meta_tool_guidance',
                                'state_contract',
                                'tool_failure_guidance',
                                'approval_guidance',
                                'reasoning_hint',
                            ])
                        )
                        .default(agentApplicationsRevisionsCreateBodySpecFrameworkPromptOmitDefault),
                    version_pin: zod
                        .number()
                        .gt(agentApplicationsRevisionsCreateBodySpecFrameworkPromptVersionPinExclusiveMin)
                        .max(agentApplicationsRevisionsCreateBodySpecFrameworkPromptVersionPinMax)
                        .optional(),
                })
                .optional(),
            resume: zod
                .object({
                    enabled: zod.boolean().default(agentApplicationsRevisionsCreateBodySpecResumeEnabledDefault),
                    max_completed_age_ms: zod
                        .number()
                        .gt(agentApplicationsRevisionsCreateBodySpecResumeMaxCompletedAgeMsExclusiveMin)
                        .max(agentApplicationsRevisionsCreateBodySpecResumeMaxCompletedAgeMsMax)
                        .default(agentApplicationsRevisionsCreateBodySpecResumeMaxCompletedAgeMsDefault),
                })
                .optional(),
        })
        .optional(),
})

/**
 * Spec edits are only allowed while state='draft'. Once promoted to
 * ready/live the spec is frozen — change requires a new revision.
 */
export const agentApplicationsRevisionsUpdateBodyBundleUriDefault = ``
export const agentApplicationsRevisionsUpdateBodySpecModelsOneLevelDefault = `medium`
export const agentApplicationsRevisionsUpdateBodySpecModelsOneOptimizeForDefault = `cost`

export const agentApplicationsRevisionsUpdateBodySpecModelsTwoModelsItemModelRegExp = new RegExp(
    '^[a-z0-9_-]+\/[a-zA-Z0-9._:-]+$'
)

export const agentApplicationsRevisionsUpdateBodySpecModelsTwoOptimizeForDefault = `cost`
export const agentApplicationsRevisionsUpdateBodySpecModelsDefault = {
    mode: 'auto' as const,
    level: 'medium' as const,
    optimize_for: 'cost' as const,
}
export const agentApplicationsRevisionsUpdateBodySpecTriggersItemOneConfigMentionOnlyDefault = false
export const agentApplicationsRevisionsUpdateBodySpecTriggersItemOneConfigAutoResumeThreadsDefault = false
export const agentApplicationsRevisionsUpdateBodySpecTriggersItemOneConfigAllowWorkspaceParticipantsDefault = false
export const agentApplicationsRevisionsUpdateBodySpecTriggersItemOneConfigAllowDirectMessagesDefault = false
export const agentApplicationsRevisionsUpdateBodySpecTriggersItemTwoAuthModesItemTwoScopesDefault = []
export const agentApplicationsRevisionsUpdateBodySpecTriggersItemTwoAuthModesItemTwoAudienceDefault = `project`

export const agentApplicationsRevisionsUpdateBodySpecTriggersItemThreeConfigTimezoneDefault = `UTC`
export const agentApplicationsRevisionsUpdateBodySpecTriggersItemThreeConfigPromptMax = 4096

export const agentApplicationsRevisionsUpdateBodySpecTriggersItemThreeConfigCatchUpDefault = `most_recent`
export const agentApplicationsRevisionsUpdateBodySpecTriggersItemThreeConfigMaxCatchUpAgeSecondsDefault = 3600
export const agentApplicationsRevisionsUpdateBodySpecTriggersItemThreeConfigMaxCatchUpAgeSecondsMax = 604800

export const agentApplicationsRevisionsUpdateBodySpecTriggersItemFourConfigAllowRestartDefault = false
export const agentApplicationsRevisionsUpdateBodySpecTriggersItemFourConfigDefault = { allow_restart: false }
export const agentApplicationsRevisionsUpdateBodySpecTriggersItemFourAuthModesItemTwoScopesDefault = []
export const agentApplicationsRevisionsUpdateBodySpecTriggersItemFourAuthModesItemTwoAudienceDefault = `project`

export const agentApplicationsRevisionsUpdateBodySpecTriggersItemFiveConfigAllowRestartDefault = false
export const agentApplicationsRevisionsUpdateBodySpecTriggersItemFiveConfigDefault = { allow_restart: false }
export const agentApplicationsRevisionsUpdateBodySpecTriggersItemFiveAuthModesItemTwoScopesDefault = []
export const agentApplicationsRevisionsUpdateBodySpecTriggersItemFiveAuthModesItemTwoAudienceDefault = `project`

export const agentApplicationsRevisionsUpdateBodySpecTriggersDefault = []
export const agentApplicationsRevisionsUpdateBodySpecToolsItemOneRequiresApprovalDefault = false
export const agentApplicationsRevisionsUpdateBodySpecToolsItemOneApprovalPolicyTypeDefault = `principal`
export const agentApplicationsRevisionsUpdateBodySpecToolsItemOneApprovalPolicyAllowEditDefault = false
export const agentApplicationsRevisionsUpdateBodySpecToolsItemOneApprovalPolicyTtlMsDefault = 86400000
export const agentApplicationsRevisionsUpdateBodySpecToolsItemOneApprovalPolicyTtlMsMin = 60000
export const agentApplicationsRevisionsUpdateBodySpecToolsItemOneApprovalPolicyTtlMsMax = 604800000

export const agentApplicationsRevisionsUpdateBodySpecToolsItemTwoRequiresApprovalDefault = false
export const agentApplicationsRevisionsUpdateBodySpecToolsItemTwoApprovalPolicyTypeDefault = `principal`
export const agentApplicationsRevisionsUpdateBodySpecToolsItemTwoApprovalPolicyAllowEditDefault = false
export const agentApplicationsRevisionsUpdateBodySpecToolsItemTwoApprovalPolicyTtlMsDefault = 86400000
export const agentApplicationsRevisionsUpdateBodySpecToolsItemTwoApprovalPolicyTtlMsMin = 60000
export const agentApplicationsRevisionsUpdateBodySpecToolsItemTwoApprovalPolicyTtlMsMax = 604800000

export const agentApplicationsRevisionsUpdateBodySpecToolsItemFourArgsSchemaDefault = {}
export const agentApplicationsRevisionsUpdateBodySpecToolsItemFourRequiredDefault = false
export const agentApplicationsRevisionsUpdateBodySpecToolsItemFourTimeoutMsDefault = 5000
export const agentApplicationsRevisionsUpdateBodySpecToolsItemFourTimeoutMsMax = 600000

export const agentApplicationsRevisionsUpdateBodySpecToolsItemFourInteractiveDefault = false
export const agentApplicationsRevisionsUpdateBodySpecToolsDefault = []
export const agentApplicationsRevisionsUpdateBodySpecMcpsItemSecretsDefault = []

export const agentApplicationsRevisionsUpdateBodySpecMcpsItemToolsItemTwoRequiresApprovalDefault = false
export const agentApplicationsRevisionsUpdateBodySpecMcpsItemToolsItemTwoApprovalPolicyTypeDefault = `principal`
export const agentApplicationsRevisionsUpdateBodySpecMcpsItemToolsItemTwoApprovalPolicyAllowEditDefault = false
export const agentApplicationsRevisionsUpdateBodySpecMcpsItemToolsItemTwoApprovalPolicyTtlMsDefault = 86400000
export const agentApplicationsRevisionsUpdateBodySpecMcpsItemToolsItemTwoApprovalPolicyTtlMsMin = 60000
export const agentApplicationsRevisionsUpdateBodySpecMcpsItemToolsItemTwoApprovalPolicyTtlMsMax = 604800000

export const agentApplicationsRevisionsUpdateBodySpecMcpsDefault = []
export const agentApplicationsRevisionsUpdateBodySpecSkillsDefault = []
export const agentApplicationsRevisionsUpdateBodySpecIdentityProvidersItemOneIdDefault = `posthog`

export const agentApplicationsRevisionsUpdateBodySpecIdentityProvidersItemOneBindingDefault = `principal`
export const agentApplicationsRevisionsUpdateBodySpecIdentityProvidersItemOneScopesDefault = []
export const agentApplicationsRevisionsUpdateBodySpecIdentityProvidersItemTwoBindingDefault = `principal`
export const agentApplicationsRevisionsUpdateBodySpecIdentityProvidersItemTwoScopesDefault = []
export const agentApplicationsRevisionsUpdateBodySpecIdentityProvidersDefault = []

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

export const agentApplicationsRevisionsUpdateBodySpecLimitsMaxOutputTokensExclusiveMin = 0
export const agentApplicationsRevisionsUpdateBodySpecLimitsMaxOutputTokensMax = 200000

export const agentApplicationsRevisionsUpdateBodySpecLimitsMaxMemoryMbDefault = 512
export const agentApplicationsRevisionsUpdateBodySpecLimitsMaxMemoryMbExclusiveMin = 0
export const agentApplicationsRevisionsUpdateBodySpecLimitsMaxMemoryMbMax = 16384

export const agentApplicationsRevisionsUpdateBodySpecLimitsMaxCpuCoresDefault = 0.25
export const agentApplicationsRevisionsUpdateBodySpecLimitsMaxCpuCoresExclusiveMin = 0
export const agentApplicationsRevisionsUpdateBodySpecLimitsMaxCpuCoresMax = 8

export const agentApplicationsRevisionsUpdateBodySpecLimitsDefault = {
    max_turns: 50,
    max_tool_calls: 200,
    max_wall_seconds: 900,
    max_memory_mb: 512,
    max_cpu_cores: 0.25,
}
export const agentApplicationsRevisionsUpdateBodySpecFrameworkPromptOmitDefault = []
export const agentApplicationsRevisionsUpdateBodySpecFrameworkPromptVersionPinExclusiveMin = 0
export const agentApplicationsRevisionsUpdateBodySpecFrameworkPromptVersionPinMax = 2147483647

export const agentApplicationsRevisionsUpdateBodySpecResumeEnabledDefault = false
export const agentApplicationsRevisionsUpdateBodySpecResumeMaxCompletedAgeMsDefault = 604800000
export const agentApplicationsRevisionsUpdateBodySpecResumeMaxCompletedAgeMsExclusiveMin = 0
export const agentApplicationsRevisionsUpdateBodySpecResumeMaxCompletedAgeMsMax = 2147483647

export const AgentApplicationsRevisionsUpdateBody = /* @__PURE__ */ zod.object({
    parent_revision: zod.uuid().nullish(),
    bundle_uri: zod
        .string()
        .default(agentApplicationsRevisionsUpdateBodyBundleUriDefault)
        .describe(
            'Storage-prefix metadata for the bundle, e.g. `fs:\/\/my-agent\/`. Optional — leave blank and the server fills `fs:\/\/<application-slug>\/`. Bundles are addressed by revision id regardless, so this is only a prefix hint.'
        ),
    spec: zod
        .object({
            models: zod
                .union([
                    zod.object({
                        mode: zod.literal('auto'),
                        level: zod
                            .enum(['low', 'medium', 'high'])
                            .default(agentApplicationsRevisionsUpdateBodySpecModelsOneLevelDefault)
                            .describe(
                                'Quality\/cost tier (auto). low = cheapest, for short, formulaic, no-reasoning jobs (lookups, FAQ bots); medium = balanced default, for multi-step but bounded work; high = top-tier, for long, branching, reasoning-heavy work. Resolved to a priority-ordered cross-provider list at session start.'
                            ),
                        reasoning: zod
                            .enum(['minimal', 'low', 'medium', 'high', 'xhigh'])
                            .optional()
                            .describe(
                                'Reasoning\/thinking effort budget. minimal = no deliberation (fastest, cheapest) … xhigh = maximal (research-grade, ~5-10x the per-turn cost). Omit for the provider\/spec default.'
                            ),
                        optimize_for: zod
                            .enum(['cost', 'availability'])
                            .default(agentApplicationsRevisionsUpdateBodySpecModelsOneOptimizeForDefault)
                            .describe(
                                "Session model stability vs. resilience. `cost` (default): the first turn picks a working model and PINS it for the whole session — keeps the provider's prompt cache warm (cache reads are ~0.1-0.5x of full input) and never fails over mid-session; if the pinned model is down the turn fails rather than re-reading the whole context cold on another provider. `availability`: fail over to the next model when the session's model fails — survives an outage at the cost of a one-time cold re-read. Prefer `cost` for long\/expensive sessions, `availability` where uptime matters more than spend."
                            ),
                    }),
                    zod.object({
                        mode: zod.literal('manual'),
                        models: zod
                            .array(
                                zod.object({
                                    model: zod
                                        .string()
                                        .min(1)
                                        .regex(agentApplicationsRevisionsUpdateBodySpecModelsTwoModelsItemModelRegExp)
                                        .describe(
                                            'Canonical model id, e.g. `anthropic\/claude-sonnet-4-6` (see the agent-applications-models tool for served ids).'
                                        ),
                                    reasoning: zod
                                        .enum(['minimal', 'low', 'medium', 'high', 'xhigh'])
                                        .optional()
                                        .describe('Per-model reasoning effort override (else the spec default).'),
                                })
                            )
                            .min(1)
                            .describe(
                                'Explicit priority-ordered fallback list — the runner tries entries in order (primary first).'
                            ),
                        optimize_for: zod
                            .enum(['cost', 'availability'])
                            .default(agentApplicationsRevisionsUpdateBodySpecModelsTwoOptimizeForDefault)
                            .describe(
                                "Session model stability vs. resilience. `cost` (default): pin the first working model for the whole session (warm prompt cache, no mid-session failover). `availability`: fail over down this list when the session's model fails (survives outages, re-reads context cold)."
                            ),
                    }),
                ])
                .default(agentApplicationsRevisionsUpdateBodySpecModelsDefault)
                .describe(
                    "How this agent selects its model. `auto`: pick a quality\/cost `level` and the platform resolves it to a maintained, priority-ordered, cross-provider list at runtime. `manual`: give an explicit priority-ordered `models` list (primary first). `optimize_for` governs how the chosen model is treated across the session's turns."
                ),
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
                                auto_resume_threads: zod
                                    .boolean()
                                    .default(
                                        agentApplicationsRevisionsUpdateBodySpecTriggersItemOneConfigAutoResumeThreadsDefault
                                    ),
                                allow_workspace_participants: zod
                                    .boolean()
                                    .default(
                                        agentApplicationsRevisionsUpdateBodySpecTriggersItemOneConfigAllowWorkspaceParticipantsDefault
                                    ),
                                ack_reaction: zod.string().optional(),
                                allow_direct_messages: zod
                                    .boolean()
                                    .default(
                                        agentApplicationsRevisionsUpdateBodySpecTriggersItemOneConfigAllowDirectMessagesDefault
                                    ),
                                trusted_workspaces: zod.union([zod.array(zod.string()).min(1), zod.literal('*')]),
                            }),
                        }),
                        zod.object({
                            type: zod.literal('webhook'),
                            config: zod.object({
                                path: zod.string(),
                            }),
                            auth: zod.object({
                                modes: zod
                                    .array(
                                        zod.union([
                                            zod.object({
                                                type: zod.literal('public'),
                                                acknowledge_public_exposure: zod.boolean(),
                                            }),
                                            zod.object({
                                                type: zod.literal('posthog'),
                                                scopes: zod
                                                    .array(zod.string())
                                                    .default(
                                                        agentApplicationsRevisionsUpdateBodySpecTriggersItemTwoAuthModesItemTwoScopesDefault
                                                    ),
                                                audience: zod
                                                    .enum(['project', 'organization'])
                                                    .default(
                                                        agentApplicationsRevisionsUpdateBodySpecTriggersItemTwoAuthModesItemTwoAudienceDefault
                                                    ),
                                            }),
                                            zod.object({
                                                type: zod.literal('jwt'),
                                                issuer_secret_ref: zod.string().min(1),
                                            }),
                                            zod.object({
                                                type: zod.literal('shared_secret'),
                                                header: zod.string().min(1),
                                                secret_ref: zod.string().min(1),
                                            }),
                                            zod.object({
                                                type: zod.literal('posthog_internal'),
                                            }),
                                        ])
                                    )
                                    .optional(),
                            }),
                        }),
                        zod.object({
                            type: zod.literal('cron'),
                            config: zod.object({
                                name: zod.string().min(1),
                                schedule: zod.string().min(1),
                                timezone: zod
                                    .string()
                                    .default(
                                        agentApplicationsRevisionsUpdateBodySpecTriggersItemThreeConfigTimezoneDefault
                                    ),
                                prompt: zod
                                    .string()
                                    .min(1)
                                    .max(agentApplicationsRevisionsUpdateBodySpecTriggersItemThreeConfigPromptMax),
                                external_key: zod.string().optional(),
                                catch_up: zod
                                    .enum(['all', 'most_recent', 'skip'])
                                    .default(
                                        agentApplicationsRevisionsUpdateBodySpecTriggersItemThreeConfigCatchUpDefault
                                    ),
                                max_catch_up_age_seconds: zod
                                    .number()
                                    .min(1)
                                    .max(
                                        agentApplicationsRevisionsUpdateBodySpecTriggersItemThreeConfigMaxCatchUpAgeSecondsMax
                                    )
                                    .default(
                                        agentApplicationsRevisionsUpdateBodySpecTriggersItemThreeConfigMaxCatchUpAgeSecondsDefault
                                    ),
                            }),
                        }),
                        zod.object({
                            type: zod.literal('chat'),
                            config: zod
                                .object({
                                    allow_restart: zod
                                        .boolean()
                                        .default(
                                            agentApplicationsRevisionsUpdateBodySpecTriggersItemFourConfigAllowRestartDefault
                                        ),
                                })
                                .default(agentApplicationsRevisionsUpdateBodySpecTriggersItemFourConfigDefault),
                            auth: zod.object({
                                modes: zod
                                    .array(
                                        zod.union([
                                            zod.object({
                                                type: zod.literal('public'),
                                                acknowledge_public_exposure: zod.boolean(),
                                            }),
                                            zod.object({
                                                type: zod.literal('posthog'),
                                                scopes: zod
                                                    .array(zod.string())
                                                    .default(
                                                        agentApplicationsRevisionsUpdateBodySpecTriggersItemFourAuthModesItemTwoScopesDefault
                                                    ),
                                                audience: zod
                                                    .enum(['project', 'organization'])
                                                    .default(
                                                        agentApplicationsRevisionsUpdateBodySpecTriggersItemFourAuthModesItemTwoAudienceDefault
                                                    ),
                                            }),
                                            zod.object({
                                                type: zod.literal('jwt'),
                                                issuer_secret_ref: zod.string().min(1),
                                            }),
                                            zod.object({
                                                type: zod.literal('shared_secret'),
                                                header: zod.string().min(1),
                                                secret_ref: zod.string().min(1),
                                            }),
                                            zod.object({
                                                type: zod.literal('posthog_internal'),
                                            }),
                                        ])
                                    )
                                    .optional(),
                            }),
                        }),
                        zod.object({
                            type: zod.literal('mcp'),
                            config: zod
                                .object({
                                    allow_restart: zod
                                        .boolean()
                                        .default(
                                            agentApplicationsRevisionsUpdateBodySpecTriggersItemFiveConfigAllowRestartDefault
                                        ),
                                })
                                .default(agentApplicationsRevisionsUpdateBodySpecTriggersItemFiveConfigDefault),
                            auth: zod.object({
                                modes: zod
                                    .array(
                                        zod.union([
                                            zod.object({
                                                type: zod.literal('public'),
                                                acknowledge_public_exposure: zod.boolean(),
                                            }),
                                            zod.object({
                                                type: zod.literal('posthog'),
                                                scopes: zod
                                                    .array(zod.string())
                                                    .default(
                                                        agentApplicationsRevisionsUpdateBodySpecTriggersItemFiveAuthModesItemTwoScopesDefault
                                                    ),
                                                audience: zod
                                                    .enum(['project', 'organization'])
                                                    .default(
                                                        agentApplicationsRevisionsUpdateBodySpecTriggersItemFiveAuthModesItemTwoAudienceDefault
                                                    ),
                                            }),
                                            zod.object({
                                                type: zod.literal('jwt'),
                                                issuer_secret_ref: zod.string().min(1),
                                            }),
                                            zod.object({
                                                type: zod.literal('shared_secret'),
                                                header: zod.string().min(1),
                                                secret_ref: zod.string().min(1),
                                            }),
                                            zod.object({
                                                type: zod.literal('posthog_internal'),
                                            }),
                                        ])
                                    )
                                    .optional(),
                            }),
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
                            requires_approval: zod
                                .boolean()
                                .default(agentApplicationsRevisionsUpdateBodySpecToolsItemOneRequiresApprovalDefault),
                            approval_policy: zod
                                .object({
                                    type: zod
                                        .enum(['principal', 'agent'])
                                        .default(
                                            agentApplicationsRevisionsUpdateBodySpecToolsItemOneApprovalPolicyTypeDefault
                                        ),
                                    allow_edit: zod
                                        .boolean()
                                        .default(
                                            agentApplicationsRevisionsUpdateBodySpecToolsItemOneApprovalPolicyAllowEditDefault
                                        ),
                                    ttl_ms: zod
                                        .number()
                                        .min(agentApplicationsRevisionsUpdateBodySpecToolsItemOneApprovalPolicyTtlMsMin)
                                        .max(agentApplicationsRevisionsUpdateBodySpecToolsItemOneApprovalPolicyTtlMsMax)
                                        .default(
                                            agentApplicationsRevisionsUpdateBodySpecToolsItemOneApprovalPolicyTtlMsDefault
                                        ),
                                })
                                .optional(),
                        }),
                        zod.object({
                            kind: zod.literal('custom'),
                            id: zod.string(),
                            path: zod.string(),
                            requires_approval: zod
                                .boolean()
                                .default(agentApplicationsRevisionsUpdateBodySpecToolsItemTwoRequiresApprovalDefault),
                            approval_policy: zod
                                .object({
                                    type: zod
                                        .enum(['principal', 'agent'])
                                        .default(
                                            agentApplicationsRevisionsUpdateBodySpecToolsItemTwoApprovalPolicyTypeDefault
                                        ),
                                    allow_edit: zod
                                        .boolean()
                                        .default(
                                            agentApplicationsRevisionsUpdateBodySpecToolsItemTwoApprovalPolicyAllowEditDefault
                                        ),
                                    ttl_ms: zod
                                        .number()
                                        .min(agentApplicationsRevisionsUpdateBodySpecToolsItemTwoApprovalPolicyTtlMsMin)
                                        .max(agentApplicationsRevisionsUpdateBodySpecToolsItemTwoApprovalPolicyTtlMsMax)
                                        .default(
                                            agentApplicationsRevisionsUpdateBodySpecToolsItemTwoApprovalPolicyTtlMsDefault
                                        ),
                                })
                                .optional(),
                            requires_identity: zod.string().optional(),
                        }),
                        zod.object({
                            kind: zod.literal('custom_template'),
                            from_template: zod.string(),
                            alias: zod.string(),
                            version: zod.number().min(1).optional(),
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
                            interactive: zod
                                .boolean()
                                .default(agentApplicationsRevisionsUpdateBodySpecToolsItemFourInteractiveDefault),
                        }),
                    ])
                )
                .default(agentApplicationsRevisionsUpdateBodySpecToolsDefault),
            mcps: zod
                .array(
                    zod.object({
                        id: zod.string().min(1),
                        url: zod.url(),
                        auth: zod
                            .object({
                                provider: zod.string().optional(),
                            })
                            .optional(),
                        secrets: zod
                            .array(zod.string())
                            .default(agentApplicationsRevisionsUpdateBodySpecMcpsItemSecretsDefault),
                        headers: zod.record(zod.string(), zod.string()).optional(),
                        tools: zod
                            .array(
                                zod.union([
                                    zod.string().min(1),
                                    zod.object({
                                        name: zod.string().min(1),
                                        requires_approval: zod
                                            .boolean()
                                            .default(
                                                agentApplicationsRevisionsUpdateBodySpecMcpsItemToolsItemTwoRequiresApprovalDefault
                                            ),
                                        approval_policy: zod
                                            .object({
                                                type: zod
                                                    .enum(['principal', 'agent'])
                                                    .default(
                                                        agentApplicationsRevisionsUpdateBodySpecMcpsItemToolsItemTwoApprovalPolicyTypeDefault
                                                    ),
                                                allow_edit: zod
                                                    .boolean()
                                                    .default(
                                                        agentApplicationsRevisionsUpdateBodySpecMcpsItemToolsItemTwoApprovalPolicyAllowEditDefault
                                                    ),
                                                ttl_ms: zod
                                                    .number()
                                                    .min(
                                                        agentApplicationsRevisionsUpdateBodySpecMcpsItemToolsItemTwoApprovalPolicyTtlMsMin
                                                    )
                                                    .max(
                                                        agentApplicationsRevisionsUpdateBodySpecMcpsItemToolsItemTwoApprovalPolicyTtlMsMax
                                                    )
                                                    .default(
                                                        agentApplicationsRevisionsUpdateBodySpecMcpsItemToolsItemTwoApprovalPolicyTtlMsDefault
                                                    ),
                                            })
                                            .optional(),
                                    }),
                                ])
                            )
                            .optional(),
                    })
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
                        version: zod.number().min(1).optional(),
                        source_version_id: zod.string().optional(),
                    })
                )
                .default(agentApplicationsRevisionsUpdateBodySpecSkillsDefault),
            identity_providers: zod
                .array(
                    zod.union([
                        zod.object({
                            kind: zod.literal('posthog'),
                            id: zod
                                .string()
                                .min(1)
                                .default(agentApplicationsRevisionsUpdateBodySpecIdentityProvidersItemOneIdDefault),
                            binding: zod
                                .enum(['principal'])
                                .default(
                                    agentApplicationsRevisionsUpdateBodySpecIdentityProvidersItemOneBindingDefault
                                ),
                            scopes: zod
                                .array(zod.string())
                                .default(agentApplicationsRevisionsUpdateBodySpecIdentityProvidersItemOneScopesDefault),
                            client_id: zod.string().optional(),
                        }),
                        zod.object({
                            kind: zod.literal('oauth2'),
                            id: zod.string().min(1),
                            binding: zod
                                .enum(['principal'])
                                .default(
                                    agentApplicationsRevisionsUpdateBodySpecIdentityProvidersItemTwoBindingDefault
                                ),
                            authorize_url: zod.url(),
                            token_url: zod.url(),
                            client_id: zod.string().min(1),
                            client_secret_ref: zod.string().optional(),
                            scopes: zod
                                .array(zod.string())
                                .default(agentApplicationsRevisionsUpdateBodySpecIdentityProvidersItemTwoScopesDefault),
                            userinfo_url: zod.url().optional(),
                        }),
                    ])
                )
                .default(agentApplicationsRevisionsUpdateBodySpecIdentityProvidersDefault),
            secrets: zod
                .array(
                    zod.union([
                        zod.string().min(1),
                        zod.object({
                            name: zod.string().min(1),
                            allowed_hosts: zod.array(zod.string().min(1)).min(1),
                        }),
                    ])
                )
                .default(agentApplicationsRevisionsUpdateBodySpecSecretsDefault),
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
                    max_output_tokens: zod
                        .number()
                        .gt(agentApplicationsRevisionsUpdateBodySpecLimitsMaxOutputTokensExclusiveMin)
                        .max(agentApplicationsRevisionsUpdateBodySpecLimitsMaxOutputTokensMax)
                        .optional(),
                    max_memory_mb: zod
                        .number()
                        .gt(agentApplicationsRevisionsUpdateBodySpecLimitsMaxMemoryMbExclusiveMin)
                        .max(agentApplicationsRevisionsUpdateBodySpecLimitsMaxMemoryMbMax)
                        .default(agentApplicationsRevisionsUpdateBodySpecLimitsMaxMemoryMbDefault),
                    max_cpu_cores: zod
                        .number()
                        .gt(agentApplicationsRevisionsUpdateBodySpecLimitsMaxCpuCoresExclusiveMin)
                        .max(agentApplicationsRevisionsUpdateBodySpecLimitsMaxCpuCoresMax)
                        .default(agentApplicationsRevisionsUpdateBodySpecLimitsMaxCpuCoresDefault),
                })
                .default(agentApplicationsRevisionsUpdateBodySpecLimitsDefault),
            reasoning: zod.enum(['minimal', 'low', 'medium', 'high', 'xhigh']).optional(),
            framework_prompt: zod
                .object({
                    omit: zod
                        .array(
                            zod.enum([
                                'meta_tool_guidance',
                                'state_contract',
                                'tool_failure_guidance',
                                'approval_guidance',
                                'reasoning_hint',
                            ])
                        )
                        .default(agentApplicationsRevisionsUpdateBodySpecFrameworkPromptOmitDefault),
                    version_pin: zod
                        .number()
                        .gt(agentApplicationsRevisionsUpdateBodySpecFrameworkPromptVersionPinExclusiveMin)
                        .max(agentApplicationsRevisionsUpdateBodySpecFrameworkPromptVersionPinMax)
                        .optional(),
                })
                .optional(),
            resume: zod
                .object({
                    enabled: zod.boolean().default(agentApplicationsRevisionsUpdateBodySpecResumeEnabledDefault),
                    max_completed_age_ms: zod
                        .number()
                        .gt(agentApplicationsRevisionsUpdateBodySpecResumeMaxCompletedAgeMsExclusiveMin)
                        .max(agentApplicationsRevisionsUpdateBodySpecResumeMaxCompletedAgeMsMax)
                        .default(agentApplicationsRevisionsUpdateBodySpecResumeMaxCompletedAgeMsDefault),
                })
                .optional(),
        })
        .optional(),
})

/**
 * Revisions of an agent. Created in `draft`, promoted through
 * `ready → live` once the bundle has been uploaded + frozen.
 *
 * URLs (nested under an application):
 *
 *     Model CRUD:
 *         GET   .../revisions/                       list
 *         POST  .../revisions/                       create draft
 *         GET   .../revisions/<id>/                  retrieve
 *         PATCH .../revisions/<id>/                  update spec (draft only)
 *
 *     Lifecycle:
 *         POST  .../revisions/<id>/promote/          ready → live
 *         POST  .../revisions/<id>/archive/          → archived
 *         POST  .../revisions/<id>/freeze/           draft → ready (stamps sha256)
 *         POST  .../revisions/<id>/clone_from/       copy bundle from another rev
 *         POST  .../revisions/new_draft/             create draft + clone_from atomically
 *
 *     Bundle authoring (proxied to the janitor):
 *         GET    .../revisions/<id>/manifest/        list paths + sha256
 *         GET    .../revisions/<id>/file/?path=…     read one file
 *         PUT    .../revisions/<id>/file/?path=…     write one file (draft)
 *         DELETE .../revisions/<id>/file/?path=…     delete one file (draft)
 *         GET    .../revisions/<id>/bundle/          bulk pull all files
 *         PUT    .../revisions/<id>/bundle/          bulk push (replace|merge)
 */
export const agentApplicationsRevisionsPartialUpdateBodyBundleUriDefault = ``
export const agentApplicationsRevisionsPartialUpdateBodySpecModelsOneLevelDefault = `medium`
export const agentApplicationsRevisionsPartialUpdateBodySpecModelsOneOptimizeForDefault = `cost`

export const agentApplicationsRevisionsPartialUpdateBodySpecModelsTwoModelsItemModelRegExp = new RegExp(
    '^[a-z0-9_-]+\/[a-zA-Z0-9._:-]+$'
)

export const agentApplicationsRevisionsPartialUpdateBodySpecModelsTwoOptimizeForDefault = `cost`
export const agentApplicationsRevisionsPartialUpdateBodySpecModelsDefault = {
    mode: 'auto' as const,
    level: 'medium' as const,
    optimize_for: 'cost' as const,
}
export const agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemOneConfigMentionOnlyDefault = false
export const agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemOneConfigAutoResumeThreadsDefault = false
export const agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemOneConfigAllowWorkspaceParticipantsDefault = false
export const agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemOneConfigAllowDirectMessagesDefault = false
export const agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemTwoAuthModesItemTwoScopesDefault = []
export const agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemTwoAuthModesItemTwoAudienceDefault = `project`

export const agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemThreeConfigTimezoneDefault = `UTC`
export const agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemThreeConfigPromptMax = 4096

export const agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemThreeConfigCatchUpDefault = `most_recent`
export const agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemThreeConfigMaxCatchUpAgeSecondsDefault = 3600
export const agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemThreeConfigMaxCatchUpAgeSecondsMax = 604800

export const agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemFourConfigAllowRestartDefault = false
export const agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemFourConfigDefault = { allow_restart: false }
export const agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemFourAuthModesItemTwoScopesDefault = []
export const agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemFourAuthModesItemTwoAudienceDefault = `project`

export const agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemFiveConfigAllowRestartDefault = false
export const agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemFiveConfigDefault = { allow_restart: false }
export const agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemFiveAuthModesItemTwoScopesDefault = []
export const agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemFiveAuthModesItemTwoAudienceDefault = `project`

export const agentApplicationsRevisionsPartialUpdateBodySpecTriggersDefault = []
export const agentApplicationsRevisionsPartialUpdateBodySpecToolsItemOneRequiresApprovalDefault = false
export const agentApplicationsRevisionsPartialUpdateBodySpecToolsItemOneApprovalPolicyTypeDefault = `principal`
export const agentApplicationsRevisionsPartialUpdateBodySpecToolsItemOneApprovalPolicyAllowEditDefault = false
export const agentApplicationsRevisionsPartialUpdateBodySpecToolsItemOneApprovalPolicyTtlMsDefault = 86400000
export const agentApplicationsRevisionsPartialUpdateBodySpecToolsItemOneApprovalPolicyTtlMsMin = 60000
export const agentApplicationsRevisionsPartialUpdateBodySpecToolsItemOneApprovalPolicyTtlMsMax = 604800000

export const agentApplicationsRevisionsPartialUpdateBodySpecToolsItemTwoRequiresApprovalDefault = false
export const agentApplicationsRevisionsPartialUpdateBodySpecToolsItemTwoApprovalPolicyTypeDefault = `principal`
export const agentApplicationsRevisionsPartialUpdateBodySpecToolsItemTwoApprovalPolicyAllowEditDefault = false
export const agentApplicationsRevisionsPartialUpdateBodySpecToolsItemTwoApprovalPolicyTtlMsDefault = 86400000
export const agentApplicationsRevisionsPartialUpdateBodySpecToolsItemTwoApprovalPolicyTtlMsMin = 60000
export const agentApplicationsRevisionsPartialUpdateBodySpecToolsItemTwoApprovalPolicyTtlMsMax = 604800000

export const agentApplicationsRevisionsPartialUpdateBodySpecToolsItemFourArgsSchemaDefault = {}
export const agentApplicationsRevisionsPartialUpdateBodySpecToolsItemFourRequiredDefault = false
export const agentApplicationsRevisionsPartialUpdateBodySpecToolsItemFourTimeoutMsDefault = 5000
export const agentApplicationsRevisionsPartialUpdateBodySpecToolsItemFourTimeoutMsMax = 600000

export const agentApplicationsRevisionsPartialUpdateBodySpecToolsItemFourInteractiveDefault = false
export const agentApplicationsRevisionsPartialUpdateBodySpecToolsDefault = []
export const agentApplicationsRevisionsPartialUpdateBodySpecMcpsItemSecretsDefault = []

export const agentApplicationsRevisionsPartialUpdateBodySpecMcpsItemToolsItemTwoRequiresApprovalDefault = false
export const agentApplicationsRevisionsPartialUpdateBodySpecMcpsItemToolsItemTwoApprovalPolicyTypeDefault = `principal`
export const agentApplicationsRevisionsPartialUpdateBodySpecMcpsItemToolsItemTwoApprovalPolicyAllowEditDefault = false
export const agentApplicationsRevisionsPartialUpdateBodySpecMcpsItemToolsItemTwoApprovalPolicyTtlMsDefault = 86400000
export const agentApplicationsRevisionsPartialUpdateBodySpecMcpsItemToolsItemTwoApprovalPolicyTtlMsMin = 60000
export const agentApplicationsRevisionsPartialUpdateBodySpecMcpsItemToolsItemTwoApprovalPolicyTtlMsMax = 604800000

export const agentApplicationsRevisionsPartialUpdateBodySpecMcpsDefault = []
export const agentApplicationsRevisionsPartialUpdateBodySpecSkillsDefault = []
export const agentApplicationsRevisionsPartialUpdateBodySpecIdentityProvidersItemOneIdDefault = `posthog`

export const agentApplicationsRevisionsPartialUpdateBodySpecIdentityProvidersItemOneBindingDefault = `principal`
export const agentApplicationsRevisionsPartialUpdateBodySpecIdentityProvidersItemOneScopesDefault = []
export const agentApplicationsRevisionsPartialUpdateBodySpecIdentityProvidersItemTwoBindingDefault = `principal`
export const agentApplicationsRevisionsPartialUpdateBodySpecIdentityProvidersItemTwoScopesDefault = []
export const agentApplicationsRevisionsPartialUpdateBodySpecIdentityProvidersDefault = []

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

export const agentApplicationsRevisionsPartialUpdateBodySpecLimitsMaxOutputTokensExclusiveMin = 0
export const agentApplicationsRevisionsPartialUpdateBodySpecLimitsMaxOutputTokensMax = 200000

export const agentApplicationsRevisionsPartialUpdateBodySpecLimitsMaxMemoryMbDefault = 512
export const agentApplicationsRevisionsPartialUpdateBodySpecLimitsMaxMemoryMbExclusiveMin = 0
export const agentApplicationsRevisionsPartialUpdateBodySpecLimitsMaxMemoryMbMax = 16384

export const agentApplicationsRevisionsPartialUpdateBodySpecLimitsMaxCpuCoresDefault = 0.25
export const agentApplicationsRevisionsPartialUpdateBodySpecLimitsMaxCpuCoresExclusiveMin = 0
export const agentApplicationsRevisionsPartialUpdateBodySpecLimitsMaxCpuCoresMax = 8

export const agentApplicationsRevisionsPartialUpdateBodySpecLimitsDefault = {
    max_turns: 50,
    max_tool_calls: 200,
    max_wall_seconds: 900,
    max_memory_mb: 512,
    max_cpu_cores: 0.25,
}
export const agentApplicationsRevisionsPartialUpdateBodySpecFrameworkPromptOmitDefault = []
export const agentApplicationsRevisionsPartialUpdateBodySpecFrameworkPromptVersionPinExclusiveMin = 0
export const agentApplicationsRevisionsPartialUpdateBodySpecFrameworkPromptVersionPinMax = 2147483647

export const agentApplicationsRevisionsPartialUpdateBodySpecResumeEnabledDefault = false
export const agentApplicationsRevisionsPartialUpdateBodySpecResumeMaxCompletedAgeMsDefault = 604800000
export const agentApplicationsRevisionsPartialUpdateBodySpecResumeMaxCompletedAgeMsExclusiveMin = 0
export const agentApplicationsRevisionsPartialUpdateBodySpecResumeMaxCompletedAgeMsMax = 2147483647

export const AgentApplicationsRevisionsPartialUpdateBody = /* @__PURE__ */ zod.object({
    parent_revision: zod.uuid().nullish(),
    bundle_uri: zod
        .string()
        .default(agentApplicationsRevisionsPartialUpdateBodyBundleUriDefault)
        .describe(
            'Storage-prefix metadata for the bundle, e.g. `fs:\/\/my-agent\/`. Optional — leave blank and the server fills `fs:\/\/<application-slug>\/`. Bundles are addressed by revision id regardless, so this is only a prefix hint.'
        ),
    spec: zod
        .object({
            models: zod
                .union([
                    zod.object({
                        mode: zod.literal('auto'),
                        level: zod
                            .enum(['low', 'medium', 'high'])
                            .default(agentApplicationsRevisionsPartialUpdateBodySpecModelsOneLevelDefault)
                            .describe(
                                'Quality\/cost tier (auto). low = cheapest, for short, formulaic, no-reasoning jobs (lookups, FAQ bots); medium = balanced default, for multi-step but bounded work; high = top-tier, for long, branching, reasoning-heavy work. Resolved to a priority-ordered cross-provider list at session start.'
                            ),
                        reasoning: zod
                            .enum(['minimal', 'low', 'medium', 'high', 'xhigh'])
                            .optional()
                            .describe(
                                'Reasoning\/thinking effort budget. minimal = no deliberation (fastest, cheapest) … xhigh = maximal (research-grade, ~5-10x the per-turn cost). Omit for the provider\/spec default.'
                            ),
                        optimize_for: zod
                            .enum(['cost', 'availability'])
                            .default(agentApplicationsRevisionsPartialUpdateBodySpecModelsOneOptimizeForDefault)
                            .describe(
                                "Session model stability vs. resilience. `cost` (default): the first turn picks a working model and PINS it for the whole session — keeps the provider's prompt cache warm (cache reads are ~0.1-0.5x of full input) and never fails over mid-session; if the pinned model is down the turn fails rather than re-reading the whole context cold on another provider. `availability`: fail over to the next model when the session's model fails — survives an outage at the cost of a one-time cold re-read. Prefer `cost` for long\/expensive sessions, `availability` where uptime matters more than spend."
                            ),
                    }),
                    zod.object({
                        mode: zod.literal('manual'),
                        models: zod
                            .array(
                                zod.object({
                                    model: zod
                                        .string()
                                        .min(1)
                                        .regex(
                                            agentApplicationsRevisionsPartialUpdateBodySpecModelsTwoModelsItemModelRegExp
                                        )
                                        .describe(
                                            'Canonical model id, e.g. `anthropic\/claude-sonnet-4-6` (see the agent-applications-models tool for served ids).'
                                        ),
                                    reasoning: zod
                                        .enum(['minimal', 'low', 'medium', 'high', 'xhigh'])
                                        .optional()
                                        .describe('Per-model reasoning effort override (else the spec default).'),
                                })
                            )
                            .min(1)
                            .describe(
                                'Explicit priority-ordered fallback list — the runner tries entries in order (primary first).'
                            ),
                        optimize_for: zod
                            .enum(['cost', 'availability'])
                            .default(agentApplicationsRevisionsPartialUpdateBodySpecModelsTwoOptimizeForDefault)
                            .describe(
                                "Session model stability vs. resilience. `cost` (default): pin the first working model for the whole session (warm prompt cache, no mid-session failover). `availability`: fail over down this list when the session's model fails (survives outages, re-reads context cold)."
                            ),
                    }),
                ])
                .default(agentApplicationsRevisionsPartialUpdateBodySpecModelsDefault)
                .describe(
                    "How this agent selects its model. `auto`: pick a quality\/cost `level` and the platform resolves it to a maintained, priority-ordered, cross-provider list at runtime. `manual`: give an explicit priority-ordered `models` list (primary first). `optimize_for` governs how the chosen model is treated across the session's turns."
                ),
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
                                auto_resume_threads: zod
                                    .boolean()
                                    .default(
                                        agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemOneConfigAutoResumeThreadsDefault
                                    ),
                                allow_workspace_participants: zod
                                    .boolean()
                                    .default(
                                        agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemOneConfigAllowWorkspaceParticipantsDefault
                                    ),
                                ack_reaction: zod.string().optional(),
                                allow_direct_messages: zod
                                    .boolean()
                                    .default(
                                        agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemOneConfigAllowDirectMessagesDefault
                                    ),
                                trusted_workspaces: zod.union([zod.array(zod.string()).min(1), zod.literal('*')]),
                            }),
                        }),
                        zod.object({
                            type: zod.literal('webhook'),
                            config: zod.object({
                                path: zod.string(),
                            }),
                            auth: zod.object({
                                modes: zod
                                    .array(
                                        zod.union([
                                            zod.object({
                                                type: zod.literal('public'),
                                                acknowledge_public_exposure: zod.boolean(),
                                            }),
                                            zod.object({
                                                type: zod.literal('posthog'),
                                                scopes: zod
                                                    .array(zod.string())
                                                    .default(
                                                        agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemTwoAuthModesItemTwoScopesDefault
                                                    ),
                                                audience: zod
                                                    .enum(['project', 'organization'])
                                                    .default(
                                                        agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemTwoAuthModesItemTwoAudienceDefault
                                                    ),
                                            }),
                                            zod.object({
                                                type: zod.literal('jwt'),
                                                issuer_secret_ref: zod.string().min(1),
                                            }),
                                            zod.object({
                                                type: zod.literal('shared_secret'),
                                                header: zod.string().min(1),
                                                secret_ref: zod.string().min(1),
                                            }),
                                            zod.object({
                                                type: zod.literal('posthog_internal'),
                                            }),
                                        ])
                                    )
                                    .optional(),
                            }),
                        }),
                        zod.object({
                            type: zod.literal('cron'),
                            config: zod.object({
                                name: zod.string().min(1),
                                schedule: zod.string().min(1),
                                timezone: zod
                                    .string()
                                    .default(
                                        agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemThreeConfigTimezoneDefault
                                    ),
                                prompt: zod
                                    .string()
                                    .min(1)
                                    .max(
                                        agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemThreeConfigPromptMax
                                    ),
                                external_key: zod.string().optional(),
                                catch_up: zod
                                    .enum(['all', 'most_recent', 'skip'])
                                    .default(
                                        agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemThreeConfigCatchUpDefault
                                    ),
                                max_catch_up_age_seconds: zod
                                    .number()
                                    .min(1)
                                    .max(
                                        agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemThreeConfigMaxCatchUpAgeSecondsMax
                                    )
                                    .default(
                                        agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemThreeConfigMaxCatchUpAgeSecondsDefault
                                    ),
                            }),
                        }),
                        zod.object({
                            type: zod.literal('chat'),
                            config: zod
                                .object({
                                    allow_restart: zod
                                        .boolean()
                                        .default(
                                            agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemFourConfigAllowRestartDefault
                                        ),
                                })
                                .default(agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemFourConfigDefault),
                            auth: zod.object({
                                modes: zod
                                    .array(
                                        zod.union([
                                            zod.object({
                                                type: zod.literal('public'),
                                                acknowledge_public_exposure: zod.boolean(),
                                            }),
                                            zod.object({
                                                type: zod.literal('posthog'),
                                                scopes: zod
                                                    .array(zod.string())
                                                    .default(
                                                        agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemFourAuthModesItemTwoScopesDefault
                                                    ),
                                                audience: zod
                                                    .enum(['project', 'organization'])
                                                    .default(
                                                        agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemFourAuthModesItemTwoAudienceDefault
                                                    ),
                                            }),
                                            zod.object({
                                                type: zod.literal('jwt'),
                                                issuer_secret_ref: zod.string().min(1),
                                            }),
                                            zod.object({
                                                type: zod.literal('shared_secret'),
                                                header: zod.string().min(1),
                                                secret_ref: zod.string().min(1),
                                            }),
                                            zod.object({
                                                type: zod.literal('posthog_internal'),
                                            }),
                                        ])
                                    )
                                    .optional(),
                            }),
                        }),
                        zod.object({
                            type: zod.literal('mcp'),
                            config: zod
                                .object({
                                    allow_restart: zod
                                        .boolean()
                                        .default(
                                            agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemFiveConfigAllowRestartDefault
                                        ),
                                })
                                .default(agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemFiveConfigDefault),
                            auth: zod.object({
                                modes: zod
                                    .array(
                                        zod.union([
                                            zod.object({
                                                type: zod.literal('public'),
                                                acknowledge_public_exposure: zod.boolean(),
                                            }),
                                            zod.object({
                                                type: zod.literal('posthog'),
                                                scopes: zod
                                                    .array(zod.string())
                                                    .default(
                                                        agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemFiveAuthModesItemTwoScopesDefault
                                                    ),
                                                audience: zod
                                                    .enum(['project', 'organization'])
                                                    .default(
                                                        agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemFiveAuthModesItemTwoAudienceDefault
                                                    ),
                                            }),
                                            zod.object({
                                                type: zod.literal('jwt'),
                                                issuer_secret_ref: zod.string().min(1),
                                            }),
                                            zod.object({
                                                type: zod.literal('shared_secret'),
                                                header: zod.string().min(1),
                                                secret_ref: zod.string().min(1),
                                            }),
                                            zod.object({
                                                type: zod.literal('posthog_internal'),
                                            }),
                                        ])
                                    )
                                    .optional(),
                            }),
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
                            requires_approval: zod
                                .boolean()
                                .default(
                                    agentApplicationsRevisionsPartialUpdateBodySpecToolsItemOneRequiresApprovalDefault
                                ),
                            approval_policy: zod
                                .object({
                                    type: zod
                                        .enum(['principal', 'agent'])
                                        .default(
                                            agentApplicationsRevisionsPartialUpdateBodySpecToolsItemOneApprovalPolicyTypeDefault
                                        ),
                                    allow_edit: zod
                                        .boolean()
                                        .default(
                                            agentApplicationsRevisionsPartialUpdateBodySpecToolsItemOneApprovalPolicyAllowEditDefault
                                        ),
                                    ttl_ms: zod
                                        .number()
                                        .min(
                                            agentApplicationsRevisionsPartialUpdateBodySpecToolsItemOneApprovalPolicyTtlMsMin
                                        )
                                        .max(
                                            agentApplicationsRevisionsPartialUpdateBodySpecToolsItemOneApprovalPolicyTtlMsMax
                                        )
                                        .default(
                                            agentApplicationsRevisionsPartialUpdateBodySpecToolsItemOneApprovalPolicyTtlMsDefault
                                        ),
                                })
                                .optional(),
                        }),
                        zod.object({
                            kind: zod.literal('custom'),
                            id: zod.string(),
                            path: zod.string(),
                            requires_approval: zod
                                .boolean()
                                .default(
                                    agentApplicationsRevisionsPartialUpdateBodySpecToolsItemTwoRequiresApprovalDefault
                                ),
                            approval_policy: zod
                                .object({
                                    type: zod
                                        .enum(['principal', 'agent'])
                                        .default(
                                            agentApplicationsRevisionsPartialUpdateBodySpecToolsItemTwoApprovalPolicyTypeDefault
                                        ),
                                    allow_edit: zod
                                        .boolean()
                                        .default(
                                            agentApplicationsRevisionsPartialUpdateBodySpecToolsItemTwoApprovalPolicyAllowEditDefault
                                        ),
                                    ttl_ms: zod
                                        .number()
                                        .min(
                                            agentApplicationsRevisionsPartialUpdateBodySpecToolsItemTwoApprovalPolicyTtlMsMin
                                        )
                                        .max(
                                            agentApplicationsRevisionsPartialUpdateBodySpecToolsItemTwoApprovalPolicyTtlMsMax
                                        )
                                        .default(
                                            agentApplicationsRevisionsPartialUpdateBodySpecToolsItemTwoApprovalPolicyTtlMsDefault
                                        ),
                                })
                                .optional(),
                            requires_identity: zod.string().optional(),
                        }),
                        zod.object({
                            kind: zod.literal('custom_template'),
                            from_template: zod.string(),
                            alias: zod.string(),
                            version: zod.number().min(1).optional(),
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
                            interactive: zod
                                .boolean()
                                .default(
                                    agentApplicationsRevisionsPartialUpdateBodySpecToolsItemFourInteractiveDefault
                                ),
                        }),
                    ])
                )
                .default(agentApplicationsRevisionsPartialUpdateBodySpecToolsDefault),
            mcps: zod
                .array(
                    zod.object({
                        id: zod.string().min(1),
                        url: zod.url(),
                        auth: zod
                            .object({
                                provider: zod.string().optional(),
                            })
                            .optional(),
                        secrets: zod
                            .array(zod.string())
                            .default(agentApplicationsRevisionsPartialUpdateBodySpecMcpsItemSecretsDefault),
                        headers: zod.record(zod.string(), zod.string()).optional(),
                        tools: zod
                            .array(
                                zod.union([
                                    zod.string().min(1),
                                    zod.object({
                                        name: zod.string().min(1),
                                        requires_approval: zod
                                            .boolean()
                                            .default(
                                                agentApplicationsRevisionsPartialUpdateBodySpecMcpsItemToolsItemTwoRequiresApprovalDefault
                                            ),
                                        approval_policy: zod
                                            .object({
                                                type: zod
                                                    .enum(['principal', 'agent'])
                                                    .default(
                                                        agentApplicationsRevisionsPartialUpdateBodySpecMcpsItemToolsItemTwoApprovalPolicyTypeDefault
                                                    ),
                                                allow_edit: zod
                                                    .boolean()
                                                    .default(
                                                        agentApplicationsRevisionsPartialUpdateBodySpecMcpsItemToolsItemTwoApprovalPolicyAllowEditDefault
                                                    ),
                                                ttl_ms: zod
                                                    .number()
                                                    .min(
                                                        agentApplicationsRevisionsPartialUpdateBodySpecMcpsItemToolsItemTwoApprovalPolicyTtlMsMin
                                                    )
                                                    .max(
                                                        agentApplicationsRevisionsPartialUpdateBodySpecMcpsItemToolsItemTwoApprovalPolicyTtlMsMax
                                                    )
                                                    .default(
                                                        agentApplicationsRevisionsPartialUpdateBodySpecMcpsItemToolsItemTwoApprovalPolicyTtlMsDefault
                                                    ),
                                            })
                                            .optional(),
                                    }),
                                ])
                            )
                            .optional(),
                    })
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
                        version: zod.number().min(1).optional(),
                        source_version_id: zod.string().optional(),
                    })
                )
                .default(agentApplicationsRevisionsPartialUpdateBodySpecSkillsDefault),
            identity_providers: zod
                .array(
                    zod.union([
                        zod.object({
                            kind: zod.literal('posthog'),
                            id: zod
                                .string()
                                .min(1)
                                .default(
                                    agentApplicationsRevisionsPartialUpdateBodySpecIdentityProvidersItemOneIdDefault
                                ),
                            binding: zod
                                .enum(['principal'])
                                .default(
                                    agentApplicationsRevisionsPartialUpdateBodySpecIdentityProvidersItemOneBindingDefault
                                ),
                            scopes: zod
                                .array(zod.string())
                                .default(
                                    agentApplicationsRevisionsPartialUpdateBodySpecIdentityProvidersItemOneScopesDefault
                                ),
                            client_id: zod.string().optional(),
                        }),
                        zod.object({
                            kind: zod.literal('oauth2'),
                            id: zod.string().min(1),
                            binding: zod
                                .enum(['principal'])
                                .default(
                                    agentApplicationsRevisionsPartialUpdateBodySpecIdentityProvidersItemTwoBindingDefault
                                ),
                            authorize_url: zod.url(),
                            token_url: zod.url(),
                            client_id: zod.string().min(1),
                            client_secret_ref: zod.string().optional(),
                            scopes: zod
                                .array(zod.string())
                                .default(
                                    agentApplicationsRevisionsPartialUpdateBodySpecIdentityProvidersItemTwoScopesDefault
                                ),
                            userinfo_url: zod.url().optional(),
                        }),
                    ])
                )
                .default(agentApplicationsRevisionsPartialUpdateBodySpecIdentityProvidersDefault),
            secrets: zod
                .array(
                    zod.union([
                        zod.string().min(1),
                        zod.object({
                            name: zod.string().min(1),
                            allowed_hosts: zod.array(zod.string().min(1)).min(1),
                        }),
                    ])
                )
                .default(agentApplicationsRevisionsPartialUpdateBodySpecSecretsDefault),
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
                    max_output_tokens: zod
                        .number()
                        .gt(agentApplicationsRevisionsPartialUpdateBodySpecLimitsMaxOutputTokensExclusiveMin)
                        .max(agentApplicationsRevisionsPartialUpdateBodySpecLimitsMaxOutputTokensMax)
                        .optional(),
                    max_memory_mb: zod
                        .number()
                        .gt(agentApplicationsRevisionsPartialUpdateBodySpecLimitsMaxMemoryMbExclusiveMin)
                        .max(agentApplicationsRevisionsPartialUpdateBodySpecLimitsMaxMemoryMbMax)
                        .default(agentApplicationsRevisionsPartialUpdateBodySpecLimitsMaxMemoryMbDefault),
                    max_cpu_cores: zod
                        .number()
                        .gt(agentApplicationsRevisionsPartialUpdateBodySpecLimitsMaxCpuCoresExclusiveMin)
                        .max(agentApplicationsRevisionsPartialUpdateBodySpecLimitsMaxCpuCoresMax)
                        .default(agentApplicationsRevisionsPartialUpdateBodySpecLimitsMaxCpuCoresDefault),
                })
                .default(agentApplicationsRevisionsPartialUpdateBodySpecLimitsDefault),
            reasoning: zod.enum(['minimal', 'low', 'medium', 'high', 'xhigh']).optional(),
            framework_prompt: zod
                .object({
                    omit: zod
                        .array(
                            zod.enum([
                                'meta_tool_guidance',
                                'state_contract',
                                'tool_failure_guidance',
                                'approval_guidance',
                                'reasoning_hint',
                            ])
                        )
                        .default(agentApplicationsRevisionsPartialUpdateBodySpecFrameworkPromptOmitDefault),
                    version_pin: zod
                        .number()
                        .gt(agentApplicationsRevisionsPartialUpdateBodySpecFrameworkPromptVersionPinExclusiveMin)
                        .max(agentApplicationsRevisionsPartialUpdateBodySpecFrameworkPromptVersionPinMax)
                        .optional(),
                })
                .optional(),
            resume: zod
                .object({
                    enabled: zod.boolean().default(agentApplicationsRevisionsPartialUpdateBodySpecResumeEnabledDefault),
                    max_completed_age_ms: zod
                        .number()
                        .gt(agentApplicationsRevisionsPartialUpdateBodySpecResumeMaxCompletedAgeMsExclusiveMin)
                        .max(agentApplicationsRevisionsPartialUpdateBodySpecResumeMaxCompletedAgeMsMax)
                        .default(agentApplicationsRevisionsPartialUpdateBodySpecResumeMaxCompletedAgeMsDefault),
                })
                .optional(),
        })
        .optional(),
})

/**
 * Revisions of an agent. Created in `draft`, promoted through
 * `ready → live` once the bundle has been uploaded + frozen.
 *
 * URLs (nested under an application):
 *
 *     Model CRUD:
 *         GET   .../revisions/                       list
 *         POST  .../revisions/                       create draft
 *         GET   .../revisions/<id>/                  retrieve
 *         PATCH .../revisions/<id>/                  update spec (draft only)
 *
 *     Lifecycle:
 *         POST  .../revisions/<id>/promote/          ready → live
 *         POST  .../revisions/<id>/archive/          → archived
 *         POST  .../revisions/<id>/freeze/           draft → ready (stamps sha256)
 *         POST  .../revisions/<id>/clone_from/       copy bundle from another rev
 *         POST  .../revisions/new_draft/             create draft + clone_from atomically
 *
 *     Bundle authoring (proxied to the janitor):
 *         GET    .../revisions/<id>/manifest/        list paths + sha256
 *         GET    .../revisions/<id>/file/?path=…     read one file
 *         PUT    .../revisions/<id>/file/?path=…     write one file (draft)
 *         DELETE .../revisions/<id>/file/?path=…     delete one file (draft)
 *         GET    .../revisions/<id>/bundle/          bulk pull all files
 *         PUT    .../revisions/<id>/bundle/          bulk push (replace|merge)
 */
export const AgentApplicationsRevisionsAgentMdUpdateBody = /* @__PURE__ */ zod
    .object({
        content: zod.string(),
    })
    .describe('Body shape for PUT \/revisions\/<id>\/agent_md\/.')

/**
 * Full-replace the typed bundle. Anything not in the payload is
 * deleted. Tool sources are AST-checked + esbuild-compiled by the
 * janitor before any S3 writes.
 */
export const AgentApplicationsRevisionsBundleUpdateBody = /* @__PURE__ */ zod
    .object({
        agent_md: zod.string(),
        tools: zod
            .array(
                zod
                    .object({
                        description: zod.string(),
                        args_schema: zod.record(zod.string(), zod.unknown()),
                        source: zod.string(),
                    })
                    .describe('Body shape for PUT \/revisions\/<id>\/tools\/<tool_id>\/.')
            )
            .optional(),
        spec: zod.record(zod.string(), zod.unknown()),
    })
    .describe(
        'Body shape for PUT \/revisions\/<id>\/bundle\/ — the full-replace typed\npayload. Skills are not authored here: they come from the llma-skill store\nvia `skill_refs` and are materialized into the bundle at freeze.'
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
 * Fire one cron job out-of-band — the same execution path the
 * scheduler walks, but on demand. Authoring UX: the user iterates on
 * a cron prompt by clicking 'Fire now' rather than waiting for the
 * next scheduled firing. Without this, 'did my prompt do the right
 * thing?' is unanswerable until the cron actually fires.
 *
 * Idempotent via `request_id`: repeat clicks with the same id resolve
 * to the same session id rather than firing N times.
 */
export const AgentApplicationsRevisionsCronFireCreateBody = /* @__PURE__ */ zod.object({
    cron_name: zod.string().describe('`name` of the cron trigger in `spec.triggers[]` to fire.'),
    request_id: zod
        .string()
        .nullish()
        .describe(
            "Stable client-supplied id so repeated clicks of the same UI 'Fire now' button resolve to the same session id rather than firing twice. The janitor keys dedupe off `cron-manual:<rev>:<name>:<request_id>`. Omit to fire unconditionally — every call generates a fresh UUID."
        ),
})

/**
 * GET / PUT / DELETE one secret by name on this revision.
 *
 * - `GET`    → `{ key, is_set }` (never returns the value).
 * - `PUT`    → upserts `{ value }` into the env block.
 * - `DELETE` → removes the key. No-op when it wasn't set.
 *
 * Per-method scope: GET is treated as a write action so the single action
 * name maps to one consistent scope; reading whether a secret is set is
 * restricted to writers in any case.
 */
export const AgentRevisionsEnvKeysSetBody = /* @__PURE__ */ zod
    .object({
        value: zod.string(),
    })
    .describe(
        'Body shape for AgentApplicationViewSet.env_keys_set — single secret upsert.\n\nThe view merges `{KEY: value}` into the existing encrypted env block\nwithout touching other keys, so callers can set or rotate one secret\nwithout needing to read the whole block back.'
    )

/**
 * Replace this revision's encrypted env block.
 *
 * The body is `{ "env": { "<KEY>": "<value>", ... } }`. The encrypted
 * text is stored on `AgentRevision.encrypted_env`; the worker decrypts it
 * at session start via the same Fernet schedule (see
 * agent-shared/src/runtime/encryption.ts).
 */
export const AgentApplicationsRevisionsSetEnvCreateBody = /* @__PURE__ */ zod
    .object({
        env: zod.record(zod.string(), zod.string()),
    })
    .describe(
        'Body shape for AgentApplicationViewSet.set_env.\n\n`env` is a JSON object of string→string. The view encrypts it via the\nsame Fernet schedule the worker uses to decrypt.'
    )

/**
 * Full-replace the draft's store-skill references. They are resolved
 * and materialized into the bundle at freeze, not here — this only records
 * which skills (and pinned versions) the freeze should pull in.
 */
export const agentApplicationsRevisionsSkillRefsUpdateBodySkillRefsItemFromTemplateMax = 64

export const agentApplicationsRevisionsSkillRefsUpdateBodySkillRefsItemAliasMax = 64

export const agentApplicationsRevisionsSkillRefsUpdateBodySkillRefsItemAliasRegExp = new RegExp(
    '^[a-z0-9](?:[a-z0-9_-]\*[a-z0-9])?$'
)

export const AgentApplicationsRevisionsSkillRefsUpdateBody = /* @__PURE__ */ zod
    .object({
        skill_refs: zod
            .array(
                zod
                    .object({
                        from_template: zod
                            .string()
                            .max(agentApplicationsRevisionsSkillRefsUpdateBodySkillRefsItemFromTemplateMax)
                            .describe(
                                'Name of the skill in the llma-skill store to pin into this agent. Resolved at freeze to the chosen `version` and materialized into the bundle.'
                            ),
                        alias: zod
                            .string()
                            .max(agentApplicationsRevisionsSkillRefsUpdateBodySkillRefsItemAliasMax)
                            .regex(agentApplicationsRevisionsSkillRefsUpdateBodySkillRefsItemAliasRegExp)
                            .describe(
                                'Folder the resolved skill is materialized under in the bundle (`skills\/<alias>\/`). Lowercase letters, digits, hyphens or underscores, starting and ending with a letter or digit; must be unique within the revision.'
                            ),
                        version: zod
                            .number()
                            .min(1)
                            .optional()
                            .describe(
                                "Specific published version to pin. Omit to pin the store's latest version at freeze time."
                            ),
                    })
                    .describe(
                        "One reference to a versioned skill in the llma-skill store, pinned into\nthis agent's bundle at freeze."
                    )
            )
            .describe('The complete set of store-skill references for this draft; replaces any existing references.'),
    })
    .describe("Body for PUT \/revisions\/<id>\/skill_refs\/ — full-replace the draft's references.")

/**
 * Revisions of an agent. Created in `draft`, promoted through
 * `ready → live` once the bundle has been uploaded + frozen.
 *
 * URLs (nested under an application):
 *
 *     Model CRUD:
 *         GET   .../revisions/                       list
 *         POST  .../revisions/                       create draft
 *         GET   .../revisions/<id>/                  retrieve
 *         PATCH .../revisions/<id>/                  update spec (draft only)
 *
 *     Lifecycle:
 *         POST  .../revisions/<id>/promote/          ready → live
 *         POST  .../revisions/<id>/archive/          → archived
 *         POST  .../revisions/<id>/freeze/           draft → ready (stamps sha256)
 *         POST  .../revisions/<id>/clone_from/       copy bundle from another rev
 *         POST  .../revisions/new_draft/             create draft + clone_from atomically
 *
 *     Bundle authoring (proxied to the janitor):
 *         GET    .../revisions/<id>/manifest/        list paths + sha256
 *         GET    .../revisions/<id>/file/?path=…     read one file
 *         PUT    .../revisions/<id>/file/?path=…     write one file (draft)
 *         DELETE .../revisions/<id>/file/?path=…     delete one file (draft)
 *         GET    .../revisions/<id>/bundle/          bulk pull all files
 *         PUT    .../revisions/<id>/bundle/          bulk push (replace|merge)
 */
export const AgentApplicationsRevisionsSpecUpdateBody = /* @__PURE__ */ zod
    .object({
        spec: zod.record(zod.string(), zod.unknown()),
    })
    .describe(
        "Body shape for PUT \/revisions\/<id>\/spec\/. The body's `spec` object\nis the author-facing slice (skills\/tools are server-derived at freeze)."
    )

/**
 * Revisions of an agent. Created in `draft`, promoted through
 * `ready → live` once the bundle has been uploaded + frozen.
 *
 * URLs (nested under an application):
 *
 *     Model CRUD:
 *         GET   .../revisions/                       list
 *         POST  .../revisions/                       create draft
 *         GET   .../revisions/<id>/                  retrieve
 *         PATCH .../revisions/<id>/                  update spec (draft only)
 *
 *     Lifecycle:
 *         POST  .../revisions/<id>/promote/          ready → live
 *         POST  .../revisions/<id>/archive/          → archived
 *         POST  .../revisions/<id>/freeze/           draft → ready (stamps sha256)
 *         POST  .../revisions/<id>/clone_from/       copy bundle from another rev
 *         POST  .../revisions/new_draft/             create draft + clone_from atomically
 *
 *     Bundle authoring (proxied to the janitor):
 *         GET    .../revisions/<id>/manifest/        list paths + sha256
 *         GET    .../revisions/<id>/file/?path=…     read one file
 *         PUT    .../revisions/<id>/file/?path=…     write one file (draft)
 *         DELETE .../revisions/<id>/file/?path=…     delete one file (draft)
 *         GET    .../revisions/<id>/bundle/          bulk pull all files
 *         PUT    .../revisions/<id>/bundle/          bulk push (replace|merge)
 */
export const AgentApplicationsRevisionsToolsUpdateBody = /* @__PURE__ */ zod
    .object({
        description: zod.string(),
        args_schema: zod.record(zod.string(), zod.unknown()),
        source: zod.string(),
    })
    .describe('Body shape for PUT \/revisions\/<id>\/tools\/<tool_id>\/.')

/**
 * Create a fresh draft revision under `application_id` and seed it
 * from `source_revision_id`. Saves the MCP one round-trip vs the
 * explicit create + clone_from sequence.
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
 *
 * URLs:
 *     GET    /api/projects/<team>/agent_applications/             list
 *     POST   /api/projects/<team>/agent_applications/             create
 *     GET    /api/projects/<team>/agent_applications/<id|slug>/   retrieve
 *     PATCH  /api/projects/<team>/agent_applications/<id|slug>/   update
 *     DELETE /api/projects/<team>/agent_applications/<id|slug>/   archive
 *     POST   /api/projects/<team>/agent_applications/<id|slug>/set_env/        bulk replace env
 *     GET    /api/projects/<team>/agent_applications/<id|slug>/env_keys/        list set keys
 *     GET    /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  is one key set?
 *     PUT    /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  set one key
 *     DELETE /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  clear one key
 */
export const agentApplicationsUpdateBodyNameMax = 255

export const agentApplicationsUpdateBodySlugMax = 63

export const agentApplicationsUpdateBodySlugRegExp = new RegExp('^[-a-zA-Z0-9_]+$')

export const AgentApplicationsUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(agentApplicationsUpdateBodyNameMax),
    slug: zod
        .string()
        .max(agentApplicationsUpdateBodySlugMax)
        .regex(agentApplicationsUpdateBodySlugRegExp)
        .optional()
        .describe(
            'Globally-unique URL identifier. Server-minted as an opaque random slug on create; only allowlisted first-party teams may set it explicitly. Slugs live in one global namespace (domain-mode ingress routing carries no team).'
        ),
    description: zod.string().optional(),
    archived: zod.boolean().optional(),
})

/**
 * Agent applications — the deployable unit of the platform.
 *
 * URLs:
 *     GET    /api/projects/<team>/agent_applications/             list
 *     POST   /api/projects/<team>/agent_applications/             create
 *     GET    /api/projects/<team>/agent_applications/<id|slug>/   retrieve
 *     PATCH  /api/projects/<team>/agent_applications/<id|slug>/   update
 *     DELETE /api/projects/<team>/agent_applications/<id|slug>/   archive
 *     POST   /api/projects/<team>/agent_applications/<id|slug>/set_env/        bulk replace env
 *     GET    /api/projects/<team>/agent_applications/<id|slug>/env_keys/        list set keys
 *     GET    /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  is one key set?
 *     PUT    /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  set one key
 *     DELETE /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  clear one key
 */
export const agentApplicationsPartialUpdateBodyNameMax = 255

export const agentApplicationsPartialUpdateBodySlugMax = 63

export const agentApplicationsPartialUpdateBodySlugRegExp = new RegExp('^[-a-zA-Z0-9_]+$')

export const AgentApplicationsPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(agentApplicationsPartialUpdateBodyNameMax).optional(),
    slug: zod
        .string()
        .max(agentApplicationsPartialUpdateBodySlugMax)
        .regex(agentApplicationsPartialUpdateBodySlugRegExp)
        .optional()
        .describe(
            'Globally-unique URL identifier. Server-minted as an opaque random slug on create; only allowlisted first-party teams may set it explicitly. Slugs live in one global namespace (domain-mode ingress routing carries no team).'
        ),
    description: zod.string().optional(),
    archived: zod.boolean().optional(),
})

/**
 * Approve or reject a queued `agent`-type tool-approval request.
 *
 * This is the OWNER decision surface — the only PostHog-authoritative one:
 * team admins decide here, in the console. `principal`-type approvals are
 * decided by the session principal at the ingress decision API, not here.
 * The runtime side runs the tool platform-side on approve and wakes the
 * session with a synthetic tool_result either way.
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
    .describe('Body shape for POST \/agent_applications\/<id>\/approvals\/<approval_id>\/decide\/.')

/**
 * Authoring-side proxy for invoking a *draft* (or any non-live) revision.
 *
 * Closes the anonymous-draft-invoke gap: the public ingress URL refuses
 * non-live invokes that don't carry the `x-agent-preview-secret` header;
 * this proxy attaches it after authenticating the Django caller.
 *
 * URL: `/api/projects/<team>/agent_applications/<app>/preview-proxy/<rest>`
 * Auth: standard PAT / session — `agents:write` scope (POST run/send/cancel
 * is a mutating invoke; the read-only `listen` GET is `agents:read`).
 */
export const AgentApplicationsPreviewProxyBody = /* @__PURE__ */ zod
    .object({
        message: zod
            .string()
            .optional()
            .describe(
                'User message to deliver to the agent. Required for `run` (starts the session) and `send` (appends to it); ignored for `cancel` \/ `listen`.'
            ),
        session_id: zod
            .string()
            .optional()
            .describe(
                'Target session id for `send` — the running session to append the message to. Omit for `run` (a fresh session is created).'
            ),
    })
    .describe(
        'Body forwarded verbatim to the agent ingress for a \*preview\* invoke of a\nnon-live revision. The meaningful shape depends on the `rest` path segment:\n\n- `run` — `{ message }`: the user message that starts a new session.\n- `send` — `{ session_id, message }`: append a message to a running session.\n- `cancel` \/ `listen` — no body.\n\nDocuments `message` \/ `session_id` so the generated MCP tool exposes them;\nany extra keys are still forwarded as-is to ingress.'
    )
