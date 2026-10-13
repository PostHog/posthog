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
 * Surfaces topics the support AI couldn't answer from the knowledge base.
 *
 * Two list shapes controlled by the ``ticket_id`` query param:
 * - **per-ticket** (``?ticket_id=<uuid>``): individual gap rows for that ticket.
 * - **aggregated** (no ``ticket_id``): gaps grouped by normalized topic with counts,
 *   for the Business knowledge suggestions panel.
 */
export const BusinessKnowledgeGapSuggestionsAcceptCreateBody = /* @__PURE__ */ zod.object({
    resolved_source_id: zod.uuid().nullish().describe('Optional knowledge source to link when accepting.'),
})

/**
 * Accept all pending suggestions for a normalized topic cluster.
 */
export const BusinessKnowledgeGapSuggestionsAcceptTopicCreateBody = /* @__PURE__ */ zod.object({
    normalized_topic: zod.string().describe('The normalized topic key identifying the gap cluster to act on.'),
    resolved_source_id: zod.uuid().nullish().describe('Optional knowledge source to link when accepting.'),
})

/**
 * Dismiss all pending suggestions for a normalized topic cluster.
 */
export const BusinessKnowledgeGapSuggestionsDismissTopicCreateBody = /* @__PURE__ */ zod.object({
    normalized_topic: zod.string().describe('The normalized topic key identifying the gap cluster to act on.'),
    resolved_source_id: zod.uuid().nullish().describe('Optional knowledge source to link when accepting.'),
})

/**
 * Append a turn and start a sandbox run. A second question in the same chat while its answer is still open returns 409. Other chats can run at the same time, up to 3 open answers per person.
 * @summary Ask a question in a playground chat
 */
export const businessKnowledgePlaygroundChatsAskCreateBodyQuestionMax = 4000

export const BusinessKnowledgePlaygroundChatsAskCreateBody = /* @__PURE__ */ zod.object({
    question: zod
        .string()
        .max(businessKnowledgePlaygroundChatsAskCreateBodyQuestionMax)
        .describe(
            "Question to answer from this project's business knowledge. Blank questions are rejected. Maximum 4000 characters."
        ),
})

/**
 * Stores the installation for this environment. Switching installations clears the selected repositories.
 * @summary Connect a GitHub installation to business knowledge
 */
export const BusinessKnowledgeRepositoriesConnectCreateBody = /* @__PURE__ */ zod.object({
    integration_id: zod.number().describe('Id of a GitHub integration on this environment.'),
})

/**
 * Every name must be a repository the connected installation can see. Names are stored lowercased.
 * @summary Replace the repositories business knowledge can read
 */
export const businessKnowledgeRepositoriesSelectionCreateBodyReposMax = 100

export const BusinessKnowledgeRepositoriesSelectionCreateBody = /* @__PURE__ */ zod.object({
    repos: zod
        .array(zod.string())
        .max(businessKnowledgeRepositoriesSelectionCreateBodyReposMax)
        .describe('owner\/repo names to allow. At most 100. Replaces the current list.'),
})

/**
 * Start a sandbox agent that can search only this project's business knowledge. Returns immediately.
 * @summary Ask a business knowledge sandbox question
 */
export const businessKnowledgeSandboxCreateBodyQuestionMax = 4000

export const BusinessKnowledgeSandboxCreateBody = /* @__PURE__ */ zod.object({
    question: zod
        .string()
        .max(businessKnowledgeSandboxCreateBodyQuestionMax)
        .describe(
            "Question to answer from this project's business knowledge. Blank questions are rejected. Maximum 4000 characters."
        ),
})

/**
 * Partially update Business knowledge learning settings. Enabling learn-from-support requires Support to be on in this environment.
 * @summary Update business knowledge settings
 */
export const BusinessKnowledgeSettingsPartialUpdateBody = /* @__PURE__ */ zod.object({
    learn_from_support_enabled: zod
        .boolean()
        .optional()
        .describe(
            'When true, PostHog learns reusable knowledge from public human replies on resolved support tickets. Rejected when Support is off for this environment.'
        ),
})

export const businessKnowledgeSourcesCreateBodyNameMax = 255

export const businessKnowledgeSourcesCreateBodyAlwaysIncludeDefault = false

export const BusinessKnowledgeSourcesCreateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(businessKnowledgeSourcesCreateBodyNameMax)
        .describe('Short human label for the source. Shown in the settings list and in agent citations.'),
    text: zod
        .string()
        .describe(
            'Raw text to index. Capped at 1 MB; larger payloads should be split into multiple sources or wait for URL\/file support in Stage 2\/3.'
        ),
    always_include: zod
        .boolean()
        .default(businessKnowledgeSourcesCreateBodyAlwaysIncludeDefault)
        .describe(
            "When true, this source's content is injected into every support reply prompt as general context (tone, policies, direction)."
        ),
})

export const businessKnowledgeSourcesPartialUpdateBodyNameMax = 255

export const BusinessKnowledgeSourcesPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .max(businessKnowledgeSourcesPartialUpdateBodyNameMax)
            .optional()
            .describe('New human label for the source.'),
        text: zod.string().optional().describe('Replacement text. Omit to keep the existing content.'),
        always_include: zod
            .boolean()
            .optional()
            .describe(
                "When true, this source's content is injected into every support reply prompt as general context."
            ),
    })
    .describe(
        'PATCH payload for text sources. All fields optional, at least one\nrequired. `text` triggers a re-chunk; `name` or `always_include` alone does not.'
    )

export const BusinessKnowledgeSourcesRefreshCreateBody = /* @__PURE__ */ zod.looseObject({})
