import { FEATURE_FLAGS, INSIGHT_ALERT_FIRING_SUB_TEMPLATE_ID } from 'lib/constants'

import {
    CyclotronJobFilterEvents,
    HogFunctionConfigurationContextId,
    HogFunctionSubTemplateIdType,
    HogFunctionSubTemplateType,
    HogFunctionTemplateType,
    PropertyFilterType,
    PropertyOperator,
    SurveyEventName,
} from '~/types'

// Deep link used in error tracking alert messages. Routes through the fingerprint redirect page
// (/error_tracking/fingerprint/<fingerprint>) so links stay valid even after issues are merged.
// Also used by the onboarding alert setup (onboardingErrorTrackingAlertsLogic) — keep the format
// in one place so URL changes can't drift between the two surfaces.
// encodeURLComponent mirrors JS encodeURIComponent, which leaves `(` and `)` unescaped — a `)` in a
// fingerprint would close the surrounding markdown link `[text](url)` early, so encode them too.
export const errorTrackingIssueLinkHogTemplate = (medium: string): string =>
    `{project.url}/error_tracking/fingerprint/{replaceAll(replaceAll(encodeURLComponent(event.properties.fingerprint), '(', '%28'), ')', '%29')}?timestamp={event.properties.exception_timestamp}&utm_source=alert&utm_campaign=error_tracking_alert&utm_medium=${medium}`

// In single-exec mode $mcp_tool_name is always the 'exec' dispatcher; the inner tool the agent
// actually invoked rides on $mcp_exec_tool_call_name, so fall back the same way the backend does.
const MCP_EFFECTIVE_TOOL_EXPR =
    'event.properties.$mcp_exec_tool_call_name ? event.properties.$mcp_exec_tool_call_name : event.properties.$mcp_tool_name'

// How long one failing tool stays deduped. Long enough to collapse a retry loop, short enough that
// a breakage that is still happening reappears in the channel.
const MCP_ALERT_MASKING_TTL_SECONDS = 30 * 60

// The masking key, which must never evaluate to an empty value: HogMaskerService skips masking
// outright when the hash expression is falsy, so an event carrying neither tool-name property (the
// filters only require $mcp_is_error, so anyone with the project token can send one) would
// otherwise escape deduplication entirely. Nameless events all collapse into one bucket instead.
const MCP_ALERT_MASKING_HASH =
    `{concat(${MCP_EFFECTIVE_TOOL_EXPR}) != '' ` + `? concat(${MCP_EFFECTIVE_TOOL_EXPR}) : 'unknown-tool'}`

// Every MCP failure notification triggers on an errored $mcp_tool_call. SDK versions stamp
// $mcp_is_error as a boolean, the string 'true', or 1, so all three encodings are matched (CDP
// compiles a multi-value Exact to IN, which the realtime bytecode rewrites to type-coercing
// comparisons). Passing `errorType` narrows to one of the semantic buckets the SDK sets on
// $mcp_error_type — see products/mcp_analytics/backend/hogql_queries/tool_tables.py for the list.
function mcpFailedToolCallEvent(errorType?: string): CyclotronJobFilterEvents {
    const properties: CyclotronJobFilterEvents['properties'] = [
        {
            key: '$mcp_is_error',
            type: PropertyFilterType.Event,
            value: ['true', true, 1],
            operator: PropertyOperator.Exact,
        },
    ]
    if (errorType) {
        properties.push({
            key: '$mcp_error_type',
            type: PropertyFilterType.Event,
            value: [errorType],
            operator: PropertyOperator.Exact,
        })
    }
    return { id: '$mcp_tool_call', type: 'events', properties }
}

// A permanently broken batch export fails every run (as often as every 5 minutes), so dedupe
// per export: one message per broken export per hour. The auto-pause threshold bounds the tail.
const BATCH_EXPORT_ALERT_MASKING_TTL_SECONDS = 60 * 60

// Keyed per batch export so two exports breaking at once both alert. The producer always sets
// batch_export_id, but HogMaskerService skips masking on falsy hashes, so fall back defensively.
const BATCH_EXPORT_ALERT_MASKING_HASH =
    "{event.properties.batch_export_id ? event.properties.batch_export_id : 'unknown-batch-export'}"

// The page a rageclick happened on: $pathname when posthog-js set it, else the full URL.
const PA_RAGECLICK_PAGE_EXPR = 'event.properties.$pathname ? event.properties.$pathname : event.properties.$current_url'

// How long rageclick alerts stay deduped — same trade-off as the MCP TTL above.
const PA_ALERT_MASKING_TTL_SECONDS = 30 * 60

// A constant key, deliberately not per-page. $pathname/$current_url are attacker-controlled
// (anyone holding the public project token can send $rageclick events), so a per-page bucket
// would let a sender mint a fresh bucket per event and flood the destination. The constant
// bounds delivery to one message per function per TTL; the message still names the page that
// triggered it, and the replay list has the rest.
const PA_RAGECLICK_MASKING_HASH = 'rageclick'

export const HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES: Record<
    HogFunctionSubTemplateIdType,
    Pick<HogFunctionSubTemplateType, 'sub_template_id' | 'type' | 'context_id'> &
        Omit<Partial<HogFunctionSubTemplateType>, 'sub_template_id' | 'type' | 'context_id'>
> = {
    'survey-response': {
        sub_template_id: 'survey-response',
        context_id: 'standard',
        type: 'destination',
        filters: {
            events: [
                {
                    id: SurveyEventName.SENT,
                    type: 'events',
                },
                {
                    id: SurveyEventName.DISMISSED,
                    type: 'events',
                },
            ],
        },
    },
    'early-access-feature-enrollment': {
        sub_template_id: 'early-access-feature-enrollment',
        type: 'destination',
        context_id: 'standard',
        filters: { events: [{ id: '$feature_enrollment_update', type: 'events' }] },
    },
    'mcp-tool-error': {
        sub_template_id: 'mcp-tool-error',
        type: 'destination',
        context_id: 'standard',
        filters: { events: [mcpFailedToolCallEvent()] },
        // Deduped per failing tool, not per call. A broken tool fails on every invocation and
        // agents retry in loops, so an undeduped alert would post a message per event — enough to
        // bury a channel, and amplifiable by anyone holding the (public) project token. One message
        // per tool per interval still surfaces each distinct breakage.
        masking: { hash: MCP_ALERT_MASKING_HASH, ttl: MCP_ALERT_MASKING_TTL_SECONDS, threshold: null },
    },
    'pa-rageclick': {
        sub_template_id: 'pa-rageclick',
        type: 'destination',
        context_id: 'standard',
        filters: { events: [{ id: '$rageclick', type: 'events' }] },
        // A broken element gets rage clicked by every visitor who hits it, so an undeduped alert
        // would post a message per event. Deduped globally (see PA_RAGECLICK_MASKING_HASH for why
        // not per-page): at most one message per interval.
        masking: { hash: PA_RAGECLICK_MASKING_HASH, ttl: PA_ALERT_MASKING_TTL_SECONDS, threshold: null },
    },
    'activity-log': {
        sub_template_id: 'activity-log',
        type: 'internal_destination',
        context_id: 'activity-log',
        filters: { events: [{ id: '$activity_log_entry_created', type: 'events' }] },
    },
    'feature-flag-change': {
        sub_template_id: 'feature-flag-change',
        type: 'internal_destination',
        context_id: 'activity-log',
        filters: {
            events: [
                {
                    id: '$activity_log_entry_created',
                    type: 'events',
                    properties: [
                        {
                            key: 'scope',
                            type: PropertyFilterType.Event,
                            value: ['FeatureFlag'],
                            operator: PropertyOperator.Exact,
                        },
                    ],
                },
            ],
        },
    },
    'discussion-mention': {
        sub_template_id: 'discussion-mention',
        type: 'internal_destination',
        context_id: 'discussion-mention',
        filters: { events: [{ id: '$discussion_mention_created', type: 'events' }] },
    },
    'error-tracking-issue-created': {
        sub_template_id: 'error-tracking-issue-created',
        type: 'internal_destination',
        context_id: 'error-tracking',
        filters: { events: [{ id: '$error_tracking_issue_created', type: 'events' }] },
    },
    'error-tracking-issue-reopened': {
        sub_template_id: 'error-tracking-issue-reopened',
        type: 'internal_destination',
        context_id: 'error-tracking',
        filters: { events: [{ id: '$error_tracking_issue_reopened', type: 'events' }] },
    },
    'error-tracking-issue-spiking': {
        sub_template_id: 'error-tracking-issue-spiking',
        type: 'internal_destination',
        context_id: 'error-tracking',
        filters: { events: [{ id: '$error_tracking_issue_spiking', type: 'events' }] },
    },
    [INSIGHT_ALERT_FIRING_SUB_TEMPLATE_ID]: {
        sub_template_id: INSIGHT_ALERT_FIRING_SUB_TEMPLATE_ID,
        type: 'internal_destination',
        context_id: 'insight-alerts',
        filters: { events: [{ id: '$insight_alert_firing', type: 'events' }] },
    },
    'experiment-significant': {
        sub_template_id: 'experiment-significant',
        type: 'internal_destination',
        context_id: 'experiment-alerts',
        filters: { events: [{ id: '$experiment_metric_significant', type: 'events' }] },
    },
    'logs-alert-firing': {
        sub_template_id: 'logs-alert-firing',
        type: 'internal_destination',
        context_id: 'logs-alerting',
        filters: { events: [{ id: '$logs_alert_firing', type: 'events' }] },
    },
    'logs-alert-resolved': {
        sub_template_id: 'logs-alert-resolved',
        type: 'internal_destination',
        context_id: 'logs-alerting',
        filters: { events: [{ id: '$logs_alert_resolved', type: 'events' }] },
    },
    'logs-alert-auto-disabled': {
        sub_template_id: 'logs-alert-auto-disabled',
        type: 'internal_destination',
        context_id: 'logs-alerting',
        filters: { events: [{ id: '$logs_alert_auto_disabled', type: 'events' }] },
    },
    'logs-alert-errored': {
        sub_template_id: 'logs-alert-errored',
        type: 'internal_destination',
        context_id: 'logs-alerting',
        filters: { events: [{ id: '$logs_alert_errored', type: 'events' }] },
    },
    'health-check-firing': {
        sub_template_id: 'health-check-firing',
        type: 'internal_destination',
        context_id: 'health-alerts',
        filters: { events: [{ id: '$health_check_issue_firing', type: 'events' }] },
    },
    'health-check-resolved': {
        sub_template_id: 'health-check-resolved',
        type: 'internal_destination',
        context_id: 'health-alerts',
        filters: { events: [{ id: '$health_check_issue_resolved', type: 'events' }] },
    },
    'batch-export-run-failed': {
        sub_template_id: 'batch-export-run-failed',
        type: 'internal_destination',
        context_id: 'batch-export-alerts',
        filters: { events: [{ id: '$batch_export_run_failed', type: 'events' }] },
        masking: {
            hash: BATCH_EXPORT_ALERT_MASKING_HASH,
            ttl: BATCH_EXPORT_ALERT_MASKING_TTL_SECONDS,
            threshold: null,
        },
        flag: FEATURE_FLAGS.BATCH_EXPORT_ALERTS,
    },
}

const FLAG_ACTOR_NAME = "{event.properties.user.first_name ? event.properties.user.first_name : 'PostHog'}"

function buildFlagChangeVerbPhrase(): string {
    const activity = 'event.properties.activity'
    const change = 'event.properties.detail.changes[1]'
    const afterGroups = `length(ifNull(${change}.after.groups, []))`
    const beforeGroups = `length(ifNull(${change}.before.groups, []))`

    const activeFieldVerb = `${change}.after == 'true' ? 'enabled' : 'disabled'`

    const filtersFieldVerb = [
        `${change}.after.multivariate != null ? 'updated variant rollout for'`,
        `${afterGroups} > ${beforeGroups} ? 'added a release condition to'`,
        `${afterGroups} < ${beforeGroups} ? 'removed a release condition from'`,
        `'updated release conditions on'`,
    ].join(' : ')

    const verbPhrase = [
        `${activity} == 'created' ? 'created'`,
        `${activity} == 'deleted' ? 'deleted'`,
        `${activity} == 'restored' ? 'restored'`,
        `${change}.field == 'active' ? (${activeFieldVerb})`,
        `${change}.field == 'filters' ? (${filtersFieldVerb})`,
        `'updated'`,
    ].join(' : ')

    return `{${verbPhrase}}`
}

const FLAG_CHANGE_VERB_PHRASE = buildFlagChangeVerbPhrase()

interface HealthAlertTemplateCopy {
    slackHeader: string
    slackBody: string
    webhookSummary: string
    discordContent: string
    teamsText: string
    actionButtonText: string
    namePrefix: string
    descriptionVerb: string
}

// Builds the destination variants for a health-alert sub-template. The body
// strings reference only the event envelope (title/summary/link/severity/kind),
// so adding a new health-check kind requires no changes here.
function buildHealthAlertSubTemplates(
    subTemplateId: 'health-check-firing' | 'health-check-resolved',
    copy: HealthAlertTemplateCopy
): HogFunctionSubTemplateType[] {
    const common = HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES[subTemplateId]
    return [
        {
            ...common,
            template_id: 'template-webhook',
            name: `HTTP webhook when a ${copy.namePrefix}`,
            description: `Send a webhook when a health check ${copy.descriptionVerb}`,
            inputs: {
                body: {
                    value: {
                        summary: copy.webhookSummary,
                        title: '{event.properties.title}',
                        message: '{event.properties.summary}',
                        kind: '{event.properties.kind}',
                        severity: '{event.properties.severity}',
                        link: '{project.url}{event.properties.link}',
                        payload: '{event.properties.payload}',
                    },
                },
            },
        },
        {
            ...common,
            template_id: 'template-slack',
            name: `Post to Slack when a ${copy.namePrefix}`,
            description: `Post to a Slack channel when a health check ${copy.descriptionVerb}`,
            inputs: {
                blocks: {
                    value: [
                        { type: 'header', text: { type: 'plain_text', text: copy.slackHeader } },
                        { type: 'section', text: { type: 'mrkdwn', text: copy.slackBody } },
                        {
                            type: 'context',
                            elements: [
                                {
                                    type: 'mrkdwn',
                                    text: 'Severity: {event.properties.severity} · Project: <{project.url}|{project.name}>',
                                },
                            ],
                        },
                        { type: 'divider' },
                        {
                            type: 'actions',
                            elements: [
                                {
                                    url: '{project.url}{event.properties.link}',
                                    text: { text: copy.actionButtonText, type: 'plain_text' },
                                    type: 'button',
                                },
                            ],
                        },
                    ],
                },
                text: { value: copy.webhookSummary },
            },
        },
        {
            ...common,
            template_id: 'template-discord',
            name: `Post to Discord when a ${copy.namePrefix}`,
            description: `Post to a Discord channel when a health check ${copy.descriptionVerb}`,
            inputs: { content: { value: copy.discordContent } },
        },
        {
            ...common,
            template_id: 'template-microsoft-teams',
            name: `Post to Microsoft Teams when a ${copy.namePrefix}`,
            description: `Post to a Microsoft Teams channel when a health check ${copy.descriptionVerb}`,
            inputs: { text: { value: copy.teamsText } },
        },
    ]
}

// All $mcp_* text is producer-controlled and unbounded, so every interpolation is escaped
// for the target chat format and truncated (post-escape, so entity expansion can't blow
// past provider message limits: Slack 3000/section, Discord 2000/message).
//
// Discord worst case: message (template text + 3 fields x 200 + intent 600, all post-escape,
// ~1260) + link (base ~80 + encoded tool name up to 480) = ~1820 < 2000.
const MCP_INTENT_MAX_LENGTH = 600
const MCP_FIELD_MAX_LENGTH = 200
// The tool name is never shortened for the link. Truncating changes the tool's identity — the
// detail page exact-matches the full event property, so a shortened link resolves to nothing —
// and cutting mid-character can leave a lone surrogate, which makes encodeURLComponent throw
// and drops the notification entirely. A name whose encoded form exceeds this budget links to
// the tool list instead: less specific, still correct.
const MCP_URL_ENCODED_TOOL_BUDGET = 480

type ChatEscaper = (expression: string, maxLength?: number) => string

/**
 * Bounds a producer-controlled value before escaping it, so the escape never scans more than it
 * can keep. Escaping only ever grows a string, so N output characters can come from at most N
 * input characters — cutting the input at the same limit leaves the bounded result identical while
 * keeping the work off a multi-megabyte property. The trailing bound still has to be applied after
 * escaping, since expansion can push a short input past the limit.
 */
function boundedExpr(expression: string, maxLength: number): string {
    return `substring(concat(${expression}), 1, ${maxLength})`
}

function slackEscapeExpr(expression: string, maxLength: number = MCP_FIELD_MAX_LENGTH): string {
    // concat, not toString: concat(null) renders '' (matching bare {} interpolation), toString(null) prints 'null'
    const bounded = boundedExpr(expression, maxLength)
    return `substring(replaceAll(replaceAll(replaceAll(${bounded}, '&', '&amp;'), '<', '&lt;'), '>', '&gt;'), 1, ${maxLength})`
}

function markdownEscapeExpr(expression: string, maxLength: number = MCP_FIELD_MAX_LENGTH): string {
    // Breaking the `](` adjacency is enough to neutralize masked links [text](url) in
    // Discord and Teams; Discord mass mentions are already suppressed by the destination
    // template's allowed_mentions, and Teams mentions can't be triggered from text.
    return `substring(replaceAll(${boundedExpr(expression, maxLength)}, '](', '] ('), 1, ${maxLength})`
}

/** The producer-controlled values a notification message interpolates. */
export type MCPMessageField = 'clientName' | 'serverName' | 'intent' | 'toolName'
type MCPFieldRenderer = (field: MCPMessageField) => string

// Renders each field as an escaped, length-bounded Hog interpolation.
function hogFieldRenderer(escape: ChatEscaper): MCPFieldRenderer {
    return (field) => {
        switch (field) {
            case 'clientName':
                return `{${escape('event.properties.$mcp_client_name')}}`
            case 'serverName':
                return `{${escape('event.properties.$mcp_server_name')}}`
            case 'intent':
                return `{${escape('event.properties.$mcp_intent', MCP_INTENT_MAX_LENGTH)}}`
            case 'toolName':
                return `{${escape(MCP_EFFECTIVE_TOOL_EXPR)}}`
        }
    }
}

// The message copy lives here once; the Hog templates and the in-app preview differ only in how
// fields are rendered, so the preview can never drift from what actually gets delivered.
function mcpToolFailureMessage(field: MCPFieldRenderer, bold: string): string {
    return (
        `${bold}${field('toolName')}${bold} failed on your MCP server ` +
        `${bold}${field('serverName')}${bold} ` +
        `(client: ${field('clientName')}). ` +
        `Agent intent: _${field('intent')}_`
    )
}

export type MCPNotificationSubTemplateId = 'mcp-tool-error'

export const MCP_NOTIFICATION_BUTTON_LABELS: Record<MCPNotificationSubTemplateId, string> = {
    'mcp-tool-error': 'View tool detail',
}

/**
 * The caps the delivered message applies to each interpolated field. Exported so a preview built
 * from real event values cuts them exactly where the chat provider will, instead of showing more
 * than actually gets sent.
 */
export const MCP_MESSAGE_FIELD_LIMITS: Record<MCPMessageField, number> = {
    clientName: MCP_FIELD_MAX_LENGTH,
    serverName: MCP_FIELD_MAX_LENGTH,
    toolName: MCP_FIELD_MAX_LENGTH,
    intent: MCP_INTENT_MAX_LENGTH,
}

/**
 * The Slack message a notification will post, rendered with sample values in place of the Hog
 * expressions — for previewing the real copy before wiring a destination up.
 */
export function mcpNotificationPreviewMessage(values: Record<MCPMessageField, string>): string {
    const field: MCPFieldRenderer = (name) => values[name]
    return mcpToolFailureMessage(field, '*')
}

const MCP_TOOL_ERROR_SLACK_MESSAGE = mcpToolFailureMessage(hogFieldRenderer(slackEscapeExpr), '*')
const MCP_TOOL_ERROR_MARKDOWN_MESSAGE = mcpToolFailureMessage(hogFieldRenderer(markdownEscapeExpr), '**')

// $pathname, $current_url and $browser are producer-controlled just like the $mcp_* properties, so
// the rageclick message reuses the same escaping and length bounds.
const PA_FIELD_MAX_LENGTH = 200

/** The producer-controlled values a rageclick notification message interpolates. */
export type PAMessageField = 'page' | 'browser'
type PAFieldRenderer = (field: PAMessageField) => string

function paHogFieldRenderer(escape: ChatEscaper): PAFieldRenderer {
    return (field) => {
        switch (field) {
            case 'page':
                return `{${escape(PA_RAGECLICK_PAGE_EXPR, PA_FIELD_MAX_LENGTH)}}`
            case 'browser':
                return `{${escape('event.properties.$browser', PA_FIELD_MAX_LENGTH)}}`
        }
    }
}

// Same single-source pattern as mcpToolFailureMessage: the Hog templates and the in-app preview
// render the one copy string, so the preview can't drift from what gets delivered.
function paRageclickMessage(field: PAFieldRenderer, bold: string): string {
    return (
        `Users are rage clicking on ${bold}${field('page')}${bold} ` +
        `(browser: ${field('browser')}). The element they're clicking isn't responding.`
    )
}

export type PANotificationSubTemplateId = 'pa-rageclick'

export const PA_NOTIFICATION_BUTTON_LABELS: Record<PANotificationSubTemplateId, string> = {
    'pa-rageclick': 'Watch session replay',
}

/** See MCP_MESSAGE_FIELD_LIMITS — the caps a preview built from real event values must apply. */
export const PA_MESSAGE_FIELD_LIMITS: Record<PAMessageField, number> = {
    page: PA_FIELD_MAX_LENGTH,
    browser: PA_FIELD_MAX_LENGTH,
}

/** See mcpNotificationPreviewMessage — the Slack message rendered with sample values. */
export function paNotificationPreviewMessage(values: Record<PAMessageField, string>): string {
    const field: PAFieldRenderer = (name) => values[name]
    return paRageclickMessage(field, '*')
}

const PA_RAGECLICK_SLACK_MESSAGE = paRageclickMessage(paHogFieldRenderer(slackEscapeExpr), '*')
const PA_RAGECLICK_MARKDOWN_MESSAGE = paRageclickMessage(paHogFieldRenderer(markdownEscapeExpr), '**')

// Session IDs are producer-controlled too: cap the encoded form like the MCP tool link does (a
// truncated ID would resolve to nothing, and a lone surrogate would make encodeURLComponent throw),
// falling back to the replay home page when the ID is missing or oversized.
const PA_ENCODED_SESSION_EXPR = 'encodeURLComponent(concat(event.properties.$session_id))'
const PA_RAGECLICK_LINK =
    `{project.url}/replay` +
    `{length(${PA_ENCODED_SESSION_EXPR}) > 0 and length(${PA_ENCODED_SESSION_EXPR}) <= ${MCP_URL_ENCODED_TOOL_BUDGET}` +
    ` ? concat('/', ${PA_ENCODED_SESSION_EXPR}) : '/home'}`

const MCP_ENCODED_EFFECTIVE_TOOL_EXPR = `encodeURLComponent(concat(${MCP_EFFECTIVE_TOOL_EXPR}))`
// Deep-links to the failing tool, falling back to the tool list when the encoded name would
// blow the Discord budget (see MCP_URL_ENCODED_TOOL_BUDGET). project.url stays a plain
// substitution so only the path suffix is conditional.
const MCP_TOOL_ERROR_LINK =
    `{project.url}/mcp-analytics/tool-quality` +
    `{length(${MCP_ENCODED_EFFECTIVE_TOOL_EXPR}) <= ${MCP_URL_ENCODED_TOOL_BUDGET}` +
    ` ? concat('/', ${MCP_ENCODED_EFFECTIVE_TOOL_EXPR}) : ''}`

interface NotificationVariantsOptions {
    subTemplateId: HogFunctionSubTemplateIdType
    nameSuffix: string
    description: string
    webhookDescription: string
    slackMessage: string
    slackFallbackText: string
    markdownMessage: string
    slackButton: { url: string; label: string }
}

function notificationVariants({
    subTemplateId,
    nameSuffix,
    description,
    webhookDescription,
    slackMessage,
    slackFallbackText,
    markdownMessage,
    slackButton,
}: NotificationVariantsOptions): HogFunctionSubTemplateType[] {
    const commonProperties = HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES[subTemplateId]

    return [
        {
            ...commonProperties,
            template_id: 'template-slack',
            name: `Post to Slack ${nameSuffix}`,
            description,
            inputs: {
                blocks: {
                    value: [
                        { type: 'section', text: { type: 'mrkdwn', text: slackMessage } },
                        {
                            type: 'actions',
                            elements: [
                                {
                                    url: slackButton.url,
                                    text: { text: slackButton.label, type: 'plain_text' },
                                    type: 'button',
                                },
                            ],
                        },
                    ],
                },
                text: { value: slackFallbackText },
            },
        },
        {
            ...commonProperties,
            template_id: 'template-microsoft-teams',
            name: `Post to Microsoft Teams ${nameSuffix}`,
            description,
            inputs: {
                text: { value: markdownMessage },
            },
        },
        {
            ...commonProperties,
            template_id: 'template-discord',
            name: `Post to Discord ${nameSuffix}`,
            description,
            inputs: {
                content: { value: markdownMessage },
            },
        },
        {
            ...commonProperties,
            template_id: 'template-webhook',
            name: `HTTP Webhook ${nameSuffix}`,
            description: webhookDescription,
        },
    ]
}

// batch_export_name is user-controlled and error can embed whatever the destination returned, so
// both get the same Slack escaping + bounds as the other producer-controlled notification fields
// (a raw value could smuggle <!channel> mentions or <url|text> masked links into the message).
// The error bound matches the backend's 1000-char truncation of the property.
const BATCH_EXPORT_NAME_SLACK = `{${slackEscapeExpr('event.properties.batch_export_name')}}`
const BATCH_EXPORT_ERROR_SLACK = `{${slackEscapeExpr('event.properties.error', 1000)}}`

export const HOG_FUNCTION_SUB_TEMPLATES: Record<HogFunctionSubTemplateIdType, HogFunctionSubTemplateType[]> = {
    'mcp-tool-error': notificationVariants({
        subTemplateId: 'mcp-tool-error',
        nameSuffix: 'when an MCP tool call fails',
        description: 'Know the moment agents hit an error on one of your tools',
        webhookDescription: 'Send failing tool calls to your own endpoint',
        slackMessage: MCP_TOOL_ERROR_SLACK_MESSAGE,
        slackFallbackText: 'An MCP tool call failed',
        markdownMessage: `${MCP_TOOL_ERROR_MARKDOWN_MESSAGE}\n\n${MCP_TOOL_ERROR_LINK}`,
        slackButton: { url: MCP_TOOL_ERROR_LINK, label: MCP_NOTIFICATION_BUTTON_LABELS['mcp-tool-error'] },
    }),
    'pa-rageclick': notificationVariants({
        subTemplateId: 'pa-rageclick',
        nameSuffix: 'when users rage click',
        description: "Know when users repeatedly click something that isn't working",
        webhookDescription: 'Send rage click events to your own endpoint',
        slackMessage: PA_RAGECLICK_SLACK_MESSAGE,
        slackFallbackText: 'Users are rage clicking',
        markdownMessage: `${PA_RAGECLICK_MARKDOWN_MESSAGE}\n\n${PA_RAGECLICK_LINK}`,
        slackButton: { url: PA_RAGECLICK_LINK, label: PA_NOTIFICATION_BUTTON_LABELS['pa-rageclick'] },
    }),
    'survey-response': [
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['survey-response'],
            template_id: 'template-webhook',
            name: 'HTTP Webhook on survey response',
            description: 'Send a webhook when a survey is completed or dismissed',
        },
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['survey-response'],
            template_id: 'template-discord',
            name: 'Post to Discord on survey response',
            description: 'Posts a message to Discord when a survey is completed or dismissed',
            inputs: {
                content: {
                    value: "**{person.name}** {event.event == 'survey dismissed' ? 'dismissed' : 'completed'} survey **{event.properties.$survey_name}**",
                },
            },
        },
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['survey-response'],
            template_id: 'template-microsoft-teams',
            name: 'Post to Microsoft Teams on survey response',
            description: 'Posts a message to Microsoft Teams when a survey is completed or dismissed',
            inputs: {
                text: {
                    value: "**{person.name}** {event.event == 'survey dismissed' ? 'dismissed' : 'completed'} survey **{event.properties.$survey_name}**",
                },
            },
        },
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['survey-response'],
            template_id: 'template-slack',
            name: 'Post to Slack on survey response',
            description: 'Posts a message to Slack when a survey is completed or dismissed',
            inputs: {
                blocks: {
                    value: [
                        {
                            text: {
                                text: "*{person.name}* {event.event == 'survey dismissed' ? 'dismissed' : 'completed'} survey *{event.properties.$survey_name}*",
                                type: 'mrkdwn',
                            },
                            type: 'section',
                        },
                        {
                            type: 'actions',
                            elements: [
                                {
                                    url: '{project.url}/surveys/{event.properties.$survey_id}',
                                    text: { text: 'View Survey', type: 'plain_text' },
                                    type: 'button',
                                },
                                {
                                    url: '{person.url}',
                                    text: { text: 'View Person', type: 'plain_text' },
                                    type: 'button',
                                },
                            ],
                        },
                    ],
                },
                text: {
                    value: "*{person.name}* {event.event == 'survey dismissed' ? 'dismissed' : 'completed'} survey *{event.properties.$survey_name}*",
                },
            },
        },
    ],
    'early-access-feature-enrollment': [
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['early-access-feature-enrollment'],
            template_id: 'template-webhook',
            name: 'HTTP Webhook on feature enrollment',
            description: 'Send a webhook when a user enrolls or un-enrolls in an early access feature',
        },
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['early-access-feature-enrollment'],
            template_id: 'template-discord',
            name: 'Post to Discord on feature enrollment',
            description: 'Posts a message to Discord when a user enrolls or un-enrolls in an early access feature',
            inputs: {
                content: {
                    value: `**{person.name}** {event.properties.$feature_enrollment ? 'enrolled in' : 'un-enrolled from'} the early access feature for '{event.properties.$feature_flag}'`,
                },
            },
        },
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['early-access-feature-enrollment'],
            template_id: 'template-microsoft-teams',
            name: 'Post to Microsoft Teams on feature enrollment',
            description:
                'Posts a message to Microsoft Teams when a user enrolls or un-enrolls in an early access feature',
            inputs: {
                text: {
                    value: `**{person.name}** {event.properties.$feature_enrollment ? 'enrolled in' : 'un-enrolled from'} the early access feature for '{event.properties.$feature_flag}'`,
                },
            },
        },
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['early-access-feature-enrollment'],
            template_id: 'template-slack',
            name: 'Post to Slack on feature enrollment',
            description: 'Posts a message to Slack when a user enrolls or un-enrolls in an early access feature',
            inputs: {
                blocks: {
                    value: [
                        {
                            text: {
                                text: "*{person.name}* {event.properties.$feature_enrollment ? 'enrolled in' : 'un-enrolled from'} the early access feature for '{event.properties.$feature_flag}'",
                                type: 'mrkdwn',
                            },
                            type: 'section',
                        },
                        {
                            type: 'actions',
                            elements: [
                                {
                                    url: '{person.url}',
                                    text: { text: 'View Person in PostHog', type: 'plain_text' },
                                    type: 'button',
                                },
                            ],
                        },
                    ],
                },
                text: {
                    value: "*{person.name}* {event.properties.$feature_enrollment ? 'enrolled in' : 'un-enrolled from'} the early access feature for '{event.properties.$feature_flag}'",
                },
            },
        },
    ],
    'activity-log': [
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['activity-log'],
            template_id: 'template-webhook',
            name: 'HTTP Webhook on team activity',
            description: 'Send a webhook when a team activity occurs',
            inputs: {
                content: {
                    value: "**{event.properties.user.first_name ? event.properties.user.first_name : 'PostHog'}** {event.properties.activity} {event.properties.scope} `{event.properties.item_id}`",
                },
            },
        },
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['activity-log'],
            template_id: 'template-discord',
            name: 'Post to Discord on team activity',
            description: 'Posts a message to Discord when a team activity occurs',
            inputs: {
                content: {
                    value: "**{event.properties.user.first_name ? event.properties.user.first_name : 'PostHog'}** {event.properties.activity} {event.properties.scope} `{event.properties.item_id}`",
                },
            },
        },
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['activity-log'],
            template_id: 'template-microsoft-teams',
            name: 'Post to Microsoft Teams on team activity',
            description: 'Posts a message to Microsoft Teams when a team activity occurs',
            inputs: {
                content: {
                    value: "**{event.properties.user.first_name ? event.properties.user.first_name : 'PostHog'}** {event.properties.activity} {event.properties.scope} `{event.properties.item_id}`",
                },
            },
        },
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['activity-log'],
            template_id: 'template-slack',
            name: 'Post to Slack on team activity',
            description: 'Posts a message to Slack when a team activity occurs',
            inputs: {
                blocks: {
                    value: [
                        {
                            text: {
                                text: "*{event.properties.user.first_name ? event.properties.user.first_name : 'PostHog'}* {event.properties.activity} {event.properties.scope} {event.properties.item_id}",
                                type: 'mrkdwn',
                            },
                            type: 'section',
                        },
                    ],
                },
                text: {
                    value: "*{event.properties.user.first_name ? event.properties.user.first_name : 'PostHog'}* {event.properties.activity} {event.properties.scope} {event.properties.item_id}",
                },
            },
        },
    ],
    'feature-flag-change': [
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['feature-flag-change'],
            template_id: 'template-webhook',
            name: 'Notify webhook for feature flag changes',
            description: 'Send a webhook when a feature flag is changed',
            inputs: {
                content: {
                    value: `**${FLAG_ACTOR_NAME}** ${FLAG_CHANGE_VERB_PHRASE} feature flag \`{event.properties.detail.name}\``,
                },
            },
        },
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['feature-flag-change'],
            template_id: 'template-discord',
            name: 'Notify Discord for feature flag changes',
            description: 'Posts a message to Discord when a feature flag is changed',
            inputs: {
                content: {
                    value: `**${FLAG_ACTOR_NAME}** ${FLAG_CHANGE_VERB_PHRASE} feature flag \`{event.properties.detail.name}\``,
                },
            },
        },
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['feature-flag-change'],
            template_id: 'template-microsoft-teams',
            name: 'Notify Microsoft Teams for feature flag changes',
            description: 'Posts a message to Microsoft Teams when a feature flag is changed',
            inputs: {
                content: {
                    value: `**${FLAG_ACTOR_NAME}** ${FLAG_CHANGE_VERB_PHRASE} feature flag \`{event.properties.detail.name}\``,
                },
            },
        },
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['feature-flag-change'],
            template_id: 'template-slack',
            name: 'Notify Slack for feature flag changes',
            description: 'Posts a message to Slack when a feature flag is changed',
            inputs: {
                blocks: {
                    value: [
                        {
                            text: {
                                text: `*${FLAG_ACTOR_NAME}* ${FLAG_CHANGE_VERB_PHRASE} feature flag \`{event.properties.detail.name}\``,
                                type: 'mrkdwn',
                            },
                            type: 'section',
                        },
                        {
                            type: 'actions',
                            elements: [
                                {
                                    url: '{project.url}/feature_flags/{event.properties.item_id}',
                                    text: { text: 'View feature flag', type: 'plain_text' },
                                    type: 'button',
                                },
                            ],
                        },
                    ],
                },
                text: {
                    value: `*${FLAG_ACTOR_NAME}* ${FLAG_CHANGE_VERB_PHRASE} feature flag \`{event.properties.detail.name}\``,
                },
            },
        },
    ],
    'discussion-mention': [
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['discussion-mention'],
            template_id: 'template-webhook',
            name: 'HTTP Webhook on discussion mention',
            description: 'Send a webhook when someone mentions you in a discussion',
        },
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['discussion-mention'],
            template_id: 'template-discord',
            name: 'Post to Discord on discussion mention',
            description: 'Posts a message to Discord when someone mentions you in a discussion',
            inputs: {
                content: {
                    value: '**{event.properties.commenter_user_name}** mentioned you in {event.properties.scope} {event.properties.item_id}',
                },
            },
        },
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['discussion-mention'],
            template_id: 'template-microsoft-teams',
            name: 'Post to Microsoft Teams on discussion mention',
            description: 'Posts a message to Microsoft Teams when someone mentions you in a discussion',
            inputs: {
                text: {
                    value: '**{event.properties.commenter_user_name}** mentioned you in {event.properties.scope} {event.properties.item_id}',
                },
            },
        },
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['discussion-mention'],
            template_id: 'template-slack',
            name: 'Post to Slack on discussion mention',
            description: 'Posts a notification to a Slack channel when someone is mentioned in a discussion',
            inputs: {
                icon_emoji: {
                    value: ':speech_balloon:',
                },
                blocks: {
                    value: [
                        {
                            text: {
                                text: '*{event.properties.commenter_user_name}* mentioned *{event.properties.mentioned_user_name}* in a discussion',
                                type: 'mrkdwn',
                            },
                            type: 'section',
                        },
                        {
                            type: 'actions',
                            elements: [
                                {
                                    url: '{event.properties.item_url}',
                                    text: { text: 'View Discussion', type: 'plain_text' },
                                    type: 'button',
                                },
                            ],
                        },
                    ],
                },
                text: {
                    value: '{event.properties.commenter_user_name} mentioned {event.properties.mentioned_user_name} in a discussion',
                },
            },
        },
    ],
    'error-tracking-issue-created': [
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['error-tracking-issue-created'],
            template_id: 'template-webhook',
            name: 'HTTP Webhook on issue created',
            description: 'Send a webhook when an issue is created',
        },
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['error-tracking-issue-created'],
            template_id: 'template-discord',
            name: 'Post to Discord on issue created',
            description: 'Posts a message to Discord when an issue is created',
            inputs: {
                content: {
                    value: `**🔴 {event.properties.name} created:** {event.properties.description}\n\n[View in PostHog](${errorTrackingIssueLinkHogTemplate('discord')})`,
                },
            },
        },
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['error-tracking-issue-created'],
            template_id: 'template-microsoft-teams',
            name: 'Post to Microsoft Teams on issue created',
            description: 'Posts a message to Microsoft Teams when an issue is created',
            inputs: {
                text: {
                    value: `**🔴 {event.properties.name} created:** {event.properties.description} (View in [PostHog](${errorTrackingIssueLinkHogTemplate('microsoft_teams')}))`,
                },
            },
        },
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['error-tracking-issue-created'],
            template_id: 'template-slack',
            name: 'Post to Slack on issue created',
            description: 'Posts a message to Slack when an issue is created',
            inputs: {
                blocks: {
                    value: [
                        { type: 'header', text: { type: 'plain_text', text: '🔴 {event.properties.name}' } },
                        { type: 'section', text: { type: 'plain_text', text: 'New issue created' } },
                        {
                            type: 'section',
                            text: { type: 'mrkdwn', text: '```{substring(event.properties.description, 1, 150)}```' },
                        },
                        {
                            type: 'context',
                            elements: [
                                { type: 'plain_text', text: 'Status: {event.properties.status}' },
                                { type: 'mrkdwn', text: 'Project: <{project.url}|{project.name}>' },
                                { type: 'mrkdwn', text: 'Alert: <{source.url}|{source.name}>' },
                            ],
                        },
                        { type: 'divider' },
                        {
                            type: 'actions',
                            elements: [
                                {
                                    url: errorTrackingIssueLinkHogTemplate('slack'),
                                    text: { text: 'View Issue', type: 'plain_text' },
                                    type: 'button',
                                },
                            ],
                        },
                    ],
                },
                text: {
                    value: 'New issue created: {event.properties.name}',
                },
            },
        },
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['error-tracking-issue-created'],
            template_id: 'template-linear',
            name: 'Linear issue on issue created',
            description: 'Create an issue in Linear when an issue is created.',
            inputs: {
                title: {
                    value: '{event.properties.name}',
                },
                description: {
                    value: '{event.properties.description}',
                },
                posthog_issue_id: {
                    value: '{event.distinct_id}',
                },
                posthog_issue_url: {
                    value: errorTrackingIssueLinkHogTemplate('linear'),
                },
            },
        },
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['error-tracking-issue-created'],
            template_id: 'template-github',
            name: 'GitHub issue on issue created',
            description: 'Create an issue in GitHub when an issue is created.',
            inputs: {
                title: {
                    value: '{event.properties.name}',
                },
                description: {
                    value: '{event.properties.description}',
                },
                posthog_issue_id: {
                    value: '{event.distinct_id}',
                },
                posthog_issue_url: {
                    value: errorTrackingIssueLinkHogTemplate('github'),
                },
            },
        },
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['error-tracking-issue-created'],
            template_id: 'template-gitlab',
            name: 'GitLab issue on issue created',
            description: 'Create an issue in GitLab when an issue is created.',
            inputs: {
                title: {
                    value: '{event.properties.name}',
                },
                description: {
                    value: '{event.properties.description}',
                },
                posthog_issue_id: {
                    value: '{event.distinct_id}',
                },
                posthog_issue_url: {
                    value: errorTrackingIssueLinkHogTemplate('gitlab'),
                },
            },
        },
    ],
    'error-tracking-issue-reopened': [
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['error-tracking-issue-reopened'],
            template_id: 'template-webhook',
            name: 'HTTP Webhook on issue reopened',
            description: 'Send a webhook when an issue is reopened',
        },
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['error-tracking-issue-reopened'],
            template_id: 'template-discord',
            name: 'Post to Discord on issue reopened',
            description: 'Posts a message to Discord when an issue is reopened',
            inputs: {
                content: {
                    value: `**🔄 {event.properties.name} reopened:** {event.properties.description}\n\n[View in PostHog](${errorTrackingIssueLinkHogTemplate('discord')})`,
                },
            },
        },
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['error-tracking-issue-reopened'],
            template_id: 'template-microsoft-teams',
            name: 'Post to Microsoft Teams on issue reopened',
            description: 'Posts a message to Microsoft Teams when an issue is reopened',
            inputs: {
                text: {
                    value: `**🔄 {event.properties.name} reopened:** {event.properties.description} (View in [PostHog](${errorTrackingIssueLinkHogTemplate('microsoft_teams')}))`,
                },
            },
        },
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['error-tracking-issue-reopened'],
            template_id: 'template-slack',
            name: 'Post to Slack on issue reopened',
            description: 'Posts a message to Slack when an issue is reopened',
            inputs: {
                blocks: {
                    value: [
                        { type: 'header', text: { type: 'plain_text', text: '🔄 {event.properties.name}' } },
                        { type: 'section', text: { type: 'plain_text', text: 'Issue reopened' } },
                        {
                            type: 'section',
                            text: { type: 'mrkdwn', text: '```{substring(event.properties.description, 1, 150)}```' },
                        },
                        {
                            type: 'context',
                            elements: [
                                { type: 'plain_text', text: 'Status: {event.properties.status}' },
                                { type: 'mrkdwn', text: 'Project: <{project.url}|{project.name}>' },
                                { type: 'mrkdwn', text: 'Alert: <{source.url}|{source.name}>' },
                            ],
                        },
                        { type: 'divider' },
                        {
                            type: 'actions',
                            elements: [
                                {
                                    url: errorTrackingIssueLinkHogTemplate('slack'),
                                    text: { text: 'View Issue', type: 'plain_text' },
                                    type: 'button',
                                },
                            ],
                        },
                    ],
                },
                text: {
                    value: 'Issue reopened: {event.properties.name}',
                },
            },
        },
    ],
    'error-tracking-issue-spiking': [
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['error-tracking-issue-spiking'],
            template_id: 'template-webhook',
            name: 'HTTP Webhook on issue spiking',
            description: 'Send a webhook when an issue is spiking',
        },
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['error-tracking-issue-spiking'],
            template_id: 'template-discord',
            name: 'Post to Discord on issue spiking',
            description: 'Posts a message to Discord when an issue is spiking',
            inputs: {
                content: {
                    value: `**📈 Issue spiking**

\`\`\`
{event.properties.name}: {substring(event.properties.description, 1, 1000)}
\`\`\`
**Exceptions in last 5 minutes:** {event.properties.current_bucket_value} ({event.properties.computed_baseline > 0 ? concat(round(event.properties.current_bucket_value / event.properties.computed_baseline), 'x over baseline') : 'no baseline yet'})
**Project:** [{project.name}]({project.url})
**Alert:** [{source.name}]({source.url})

[View issue](${errorTrackingIssueLinkHogTemplate('discord')})`,
                },
            },
        },
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['error-tracking-issue-spiking'],
            template_id: 'template-microsoft-teams',
            name: 'Post to Microsoft Teams on issue spiking',
            description: 'Posts a message to Microsoft Teams when an issue is spiking',
            inputs: {
                text: {
                    value: `**📈 Issue spiking: {event.properties.name}:** {event.properties.description}\n**Exceptions in last 5 minutes:** {event.properties.current_bucket_value} ({event.properties.computed_baseline > 0 ? concat(round(event.properties.current_bucket_value / event.properties.computed_baseline), 'x over baseline') : 'no baseline yet'}) (View in [PostHog](${errorTrackingIssueLinkHogTemplate('microsoft_teams')}))`,
                },
            },
        },
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['error-tracking-issue-spiking'],
            template_id: 'template-slack',
            name: 'Post to Slack on issue spiking',
            description: 'Posts a message to Slack when an issue is spiking',
            inputs: {
                blocks: {
                    value: [
                        { type: 'header', text: { type: 'plain_text', text: '📈 Issue spiking' } },
                        {
                            type: 'section',
                            text: {
                                type: 'mrkdwn',
                                text: '```{event.properties.name}: {substring(event.properties.description, 1, 1000)}```',
                            },
                        },
                        {
                            type: 'context',
                            elements: [
                                {
                                    type: 'plain_text',
                                    text: "Exceptions in last 5 minutes: {event.properties.current_bucket_value} ({event.properties.computed_baseline > 0 ? concat(round(event.properties.current_bucket_value / event.properties.computed_baseline), 'x over baseline') : 'no baseline yet'})",
                                },
                                { type: 'mrkdwn', text: 'Project: <{project.url}|{project.name}>' },
                                { type: 'mrkdwn', text: 'Alert: <{source.url}|{source.name}>' },
                            ],
                        },
                        { type: 'divider' },
                        {
                            type: 'actions',
                            elements: [
                                {
                                    url: errorTrackingIssueLinkHogTemplate('slack'),
                                    text: { text: 'View Issue', type: 'plain_text' },
                                    type: 'button',
                                },
                            ],
                        },
                    ],
                },
                text: {
                    value: 'Issue spiking: {event.properties.name}',
                },
            },
        },
    ],
    'experiment-significant': [
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['experiment-significant'],
            template_id: 'template-webhook',
            name: 'HTTP Webhook on experiment significance',
            description: 'Send a webhook when an experiment metric reaches significance',
        },
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['experiment-significant'],
            template_id: 'template-slack',
            name: 'Post to Slack on experiment significance',
            description: 'Post to a Slack channel when an experiment metric reaches significance',
            inputs: {
                blocks: {
                    value: [
                        {
                            type: 'header',
                            text: {
                                type: 'plain_text',
                                text: "\ud83e\uddea Experiment '{event.properties.experiment_name}' has reached significance",
                            },
                        },
                        {
                            type: 'section',
                            text: {
                                type: 'mrkdwn',
                                text: '*{event.properties.variant_key}* variant is winning on *{event.properties.metric_name}* {event.properties.relative_change}\nChance to win: *{event.properties.chance_to_win}* \u00b7 Goal: *{event.properties.goal_direction}*',
                            },
                        },
                        {
                            type: 'actions',
                            elements: [
                                {
                                    url: '{project.url}{event.properties.experiment_url}',
                                    text: { text: 'View experiment', type: 'plain_text' },
                                    type: 'button',
                                },
                            ],
                        },
                        {
                            type: 'context',
                            elements: [{ type: 'mrkdwn', text: '{project.name}' }],
                        },
                    ],
                },
                text: {
                    value: "Experiment '{event.properties.experiment_name}' has reached significance",
                },
            },
        },
    ],
    [INSIGHT_ALERT_FIRING_SUB_TEMPLATE_ID]: [
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES[INSIGHT_ALERT_FIRING_SUB_TEMPLATE_ID],
            template_id: 'template-webhook',
            name: 'HTTP Webhook on insight alert firing',
            description: 'Send a webhook when this insight alert fires',
        },
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES[INSIGHT_ALERT_FIRING_SUB_TEMPLATE_ID],
            template_id: 'template-slack',
            name: 'Post to Slack on insight alert firing',
            description: 'Post to a Slack channel when this insight alert fires',
            inputs: {
                blocks: {
                    value: [
                        {
                            type: 'header',
                            text: {
                                type: 'plain_text',
                                text: "Alert '{event.properties.alert_name}' firing for insight '{event.properties.insight_name}'",
                            },
                        },
                        {
                            // plain_text (not mrkdwn) so user-controlled names in the breach text can't
                            // inject Slack markup/links/mentions. Newlines still render as line breaks.
                            type: 'section',
                            text: {
                                type: 'plain_text',
                                text: '{event.properties.breaches}',
                            },
                        },
                        {
                            type: 'context',
                            elements: [{ type: 'mrkdwn', text: 'Project: <{project.url}|{project.name}>' }],
                        },
                        // A hog template that is a single {…} expression resolves to the expression's raw
                        // value, so this string becomes a whole block: a chart of the alerted insight when
                        // the anomaly investigation rendered one (`insight_chart_url` set by
                        // investigate_anomaly_activity), otherwise the plain divider — Slack has no way to
                        // omit a block conditionally, and an image block with an empty URL fails the send.
                        "{event.properties.insight_chart_url ? {'type': 'image', 'image_url': event.properties.insight_chart_url, 'alt_text': 'Insight chart'} : {'type': 'divider'}}",
                        {
                            type: 'actions',
                            // The alert id in the block_id is what lets the datetimepicker action identify
                            // its alert — unlike select options, datetimepicker elements carry no value.
                            block_id: 'insight_alert_snooze:{event.properties.alert_id}',
                            elements: [
                                {
                                    // Points to the anomaly investigation notebook when present, otherwise falls
                                    // back to the alert page (Slack can't conditionally hide a button, so the
                                    // one button does double duty).
                                    url: "{event.properties.investigation_notebook_url ? event.properties.investigation_notebook_url : concat(project.url, '/insights/', event.properties.insight_id, '/alerts?alert_id=', event.properties.alert_id, '&utm_source=alert&utm_campaign=alert_check_firing&utm_medium=slack')}",
                                    text: {
                                        text: "{event.properties.investigation_notebook_url ? 'View Investigation' : 'View Alert'}",
                                        type: 'plain_text',
                                    },
                                    type: 'button',
                                },
                                {
                                    url: '{project.url}/insights/{event.properties.insight_id}?utm_source=alert&utm_campaign=alert_check_firing&utm_medium=slack',
                                    text: { text: 'View Insight', type: 'plain_text' },
                                    type: 'button',
                                },
                                {
                                    action_id: 'insight_alert_snooze',
                                    placeholder: { text: 'Snooze…', type: 'plain_text' },
                                    options: [
                                        {
                                            text: { text: 'For 1 hour', type: 'plain_text' },
                                            value: '{event.properties.alert_id}|1h',
                                        },
                                        {
                                            text: { text: 'For 6 hours', type: 'plain_text' },
                                            value: '{event.properties.alert_id}|6h',
                                        },
                                        {
                                            text: { text: 'For 1 day', type: 'plain_text' },
                                            value: '{event.properties.alert_id}|1d',
                                        },
                                        {
                                            text: { text: 'For 1 week', type: 'plain_text' },
                                            value: '{event.properties.alert_id}|1w',
                                        },
                                        {
                                            text: { text: 'Pick a date & time…', type: 'plain_text' },
                                            value: '{event.properties.alert_id}|custom',
                                        },
                                    ],
                                    type: 'static_select',
                                },
                            ],
                        },
                    ],
                },
                text: {
                    value: 'Alert triggered: {event.properties.insight_name}',
                },
            },
        },
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES[INSIGHT_ALERT_FIRING_SUB_TEMPLATE_ID],
            template_id: 'template-discord',
            name: 'Post to Discord on insight alert firing',
            description: 'Post to a Discord channel when this insight alert fires',
            inputs: {
                content: {
                    value: "**Alert '{event.properties.alert_name}' firing** for insight '{event.properties.insight_name}'\n{event.properties.breaches}\n{project.url}/insights/{event.properties.insight_id}/alerts?alert_id={event.properties.alert_id}",
                },
            },
        },
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES[INSIGHT_ALERT_FIRING_SUB_TEMPLATE_ID],
            template_id: 'template-microsoft-teams',
            name: 'Post to Microsoft Teams on insight alert firing',
            description: 'Post to a Microsoft Teams channel when this insight alert fires',
            inputs: {
                text: {
                    value: "**Alert '{event.properties.alert_name}' firing** for insight '{event.properties.insight_name}'\n\n{event.properties.breaches}\n\n[View alert]({project.url}/insights/{event.properties.insight_id}/alerts?alert_id={event.properties.alert_id})",
                },
            },
        },
    ],
    'logs-alert-firing': [
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['logs-alert-firing'],
            template_id: 'template-webhook',
            name: 'HTTP Webhook on log alert firing',
            description: 'Send a webhook when a log alert fires',
        },
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['logs-alert-firing'],
            template_id: 'template-slack',
            name: 'Post to Slack on log alert firing',
            description: 'Post to a Slack channel when a log alert fires',
            inputs: {
                blocks: {
                    value: [
                        {
                            type: 'header',
                            text: {
                                type: 'plain_text',
                                text: "Log alert '{event.properties.alert_name}' is firing",
                            },
                        },
                        {
                            type: 'section',
                            text: {
                                type: 'mrkdwn',
                                text: '*Threshold breached:* {event.properties.threshold_count} logs in {event.properties.window_minutes}m (limit: {event.properties.threshold_operator} {event.properties.threshold_value})',
                            },
                        },
                        {
                            type: 'context',
                            elements: [{ type: 'mrkdwn', text: 'Project: <{project.url}|{project.name}>' }],
                        },
                        { type: 'divider' },
                        {
                            type: 'actions',
                            elements: [
                                {
                                    url: '{project.url}/logs?{event.properties.logs_url_params}&utm_source=alert&utm_campaign=logs_alert&utm_medium=slack',
                                    text: { text: 'View logs', type: 'plain_text' },
                                    type: 'button',
                                },
                            ],
                        },
                    ],
                },
                text: {
                    value: "Log alert '{event.properties.alert_name}' is firing",
                },
            },
        },
    ],
    'logs-alert-resolved': [
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['logs-alert-resolved'],
            template_id: 'template-webhook',
            name: 'HTTP Webhook on log alert resolved',
            description: 'Send a webhook when a log alert resolves',
        },
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['logs-alert-resolved'],
            template_id: 'template-slack',
            name: 'Post to Slack on log alert resolved',
            description: 'Post to a Slack channel when a log alert resolves',
            inputs: {
                blocks: {
                    value: [
                        {
                            type: 'header',
                            text: {
                                type: 'plain_text',
                                text: "Log alert '{event.properties.alert_name}' has resolved",
                            },
                        },
                        {
                            type: 'section',
                            text: {
                                type: 'mrkdwn',
                                text: '*Current count:* {event.properties.result_count} in {event.properties.window_minutes}m (threshold: {event.properties.threshold_operator} {event.properties.threshold_count})',
                            },
                        },
                        {
                            type: 'context',
                            elements: [{ type: 'mrkdwn', text: 'Project: <{project.url}|{project.name}>' }],
                        },
                        { type: 'divider' },
                        {
                            type: 'actions',
                            elements: [
                                {
                                    url: '{project.url}/logs?{event.properties.logs_url_params}&utm_source=alert&utm_campaign=logs_alert&utm_medium=slack',
                                    text: { text: 'View logs', type: 'plain_text' },
                                    type: 'button',
                                },
                            ],
                        },
                    ],
                },
                text: {
                    value: "Log alert '{event.properties.alert_name}' has resolved",
                },
            },
        },
    ],
    'logs-alert-auto-disabled': [
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['logs-alert-auto-disabled'],
            template_id: 'template-webhook',
            name: 'HTTP Webhook on log alert auto-disabled',
            description: 'Send a webhook when a log alert is auto-disabled due to repeated failures',
        },
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['logs-alert-auto-disabled'],
            template_id: 'template-slack',
            name: 'Post to Slack on log alert auto-disabled',
            description: 'Post to Slack when a log alert is auto-disabled due to repeated failures',
            inputs: {
                blocks: {
                    value: [
                        {
                            type: 'header',
                            text: {
                                type: 'plain_text',
                                text: "Log alert '{event.properties.alert_name}' was auto-disabled",
                            },
                        },
                        {
                            type: 'section',
                            text: {
                                type: 'mrkdwn',
                                text: '*Reason:* {event.properties.consecutive_failures} consecutive check failures.\n*Last error:* {event.properties.last_error_message}',
                            },
                        },
                        {
                            type: 'context',
                            elements: [{ type: 'mrkdwn', text: 'Project: <{project.url}|{project.name}>' }],
                        },
                        { type: 'divider' },
                        {
                            type: 'actions',
                            elements: [
                                {
                                    url: '{project.url}/logs?alertId={event.properties.alert_id}&utm_source=alert&utm_campaign=logs_alert&utm_medium=slack',
                                    text: { text: 'View alert', type: 'plain_text' },
                                    type: 'button',
                                },
                            ],
                        },
                    ],
                },
                text: {
                    value: "Log alert '{event.properties.alert_name}' was auto-disabled after {event.properties.consecutive_failures} consecutive failures",
                },
            },
        },
    ],
    'health-check-firing': buildHealthAlertSubTemplates('health-check-firing', {
        // Verbs/copy chosen so the same template body works for any health-check kind.
        slackHeader: '{event.properties.title}',
        slackBody: '{event.properties.summary}',
        webhookSummary: '{event.properties.title}: {event.properties.summary}',
        discordContent:
            '**🩺 PostHog health check**\n\n*{event.properties.title}*\n{event.properties.summary}\n\n[View in PostHog]({project.url}{event.properties.link})',
        teamsText:
            '**🩺 PostHog health check:** *{event.properties.title}* — {event.properties.summary} (View in [PostHog]({project.url}{event.properties.link}))',
        actionButtonText: 'View in PostHog',
        namePrefix: 'health check fires',
        descriptionVerb: 'fires',
    }),
    'health-check-resolved': buildHealthAlertSubTemplates('health-check-resolved', {
        slackHeader: 'Resolved: {event.properties.title}',
        slackBody: '{event.properties.summary}',
        webhookSummary: 'Resolved: {event.properties.title} — {event.properties.summary}',
        discordContent:
            '**✅ PostHog health check resolved**\n\n*{event.properties.title}*\n{event.properties.summary}\n\n[View in PostHog]({project.url}{event.properties.link})',
        teamsText:
            '**✅ Resolved:** *{event.properties.title}* — {event.properties.summary} (View in [PostHog]({project.url}{event.properties.link}))',
        actionButtonText: 'View in PostHog',
        namePrefix: 'health check resolves',
        descriptionVerb: 'resolves',
    }),
    'logs-alert-errored': [
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['logs-alert-errored'],
            template_id: 'template-webhook',
            name: 'HTTP Webhook on log alert evaluation error',
            description: 'Send a webhook when a log alert fails to evaluate',
        },
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['logs-alert-errored'],
            template_id: 'template-slack',
            name: 'Post to Slack on log alert evaluation error',
            description: 'Post to Slack when a log alert fails to evaluate',
            inputs: {
                blocks: {
                    value: [
                        {
                            type: 'header',
                            text: {
                                type: 'plain_text',
                                text: "Log alert '{event.properties.alert_name}' couldn't evaluate",
                            },
                        },
                        {
                            type: 'section',
                            text: {
                                type: 'mrkdwn',
                                text: '*Reason:* {event.properties.error_message}\n*Failure count:* {event.properties.consecutive_failures}',
                            },
                        },
                        {
                            type: 'context',
                            elements: [{ type: 'mrkdwn', text: 'Project: <{project.url}|{project.name}>' }],
                        },
                        { type: 'divider' },
                        {
                            type: 'actions',
                            elements: [
                                {
                                    url: '{project.url}/logs?alertId={event.properties.alert_id}&utm_source=alert&utm_campaign=logs_alert&utm_medium=slack',
                                    text: { text: 'View alert', type: 'plain_text' },
                                    type: 'button',
                                },
                            ],
                        },
                    ],
                },
                text: {
                    value: "Log alert '{event.properties.alert_name}' couldn't evaluate: {event.properties.error_message}",
                },
            },
        },
    ],
    'batch-export-run-failed': [
        {
            ...HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['batch-export-run-failed'],
            template_id: 'template-slack',
            name: 'Post to Slack on batch export failure',
            description: 'Post to a Slack channel when a batch export run fails',
            inputs: {
                blocks: {
                    value: [
                        { type: 'header', text: { type: 'plain_text', text: 'Batch export failed' } },
                        {
                            type: 'section',
                            text: {
                                type: 'mrkdwn',
                                // data_interval_start is null for backfill runs covering everything
                                // up to the end date ("beginning of time" in the backfills UI)
                                text: `*${BATCH_EXPORT_NAME_SLACK}* ({event.properties.destination_type}) failed to export data for {event.properties.data_interval_start ? event.properties.data_interval_start : 'the beginning of time'} – {event.properties.data_interval_end}.`,
                            },
                        },
                        {
                            type: 'section',
                            text: { type: 'mrkdwn', text: `*Error:* ${BATCH_EXPORT_ERROR_SLACK}` },
                        },
                        {
                            type: 'context',
                            elements: [{ type: 'mrkdwn', text: 'Project: <{project.url}|{project.name}>' }],
                        },
                        { type: 'divider' },
                        {
                            type: 'actions',
                            elements: [
                                {
                                    url: '{project.url}/pipeline/batch-exports/{event.properties.batch_export_id}',
                                    text: { text: 'View batch export', type: 'plain_text' },
                                    type: 'button',
                                },
                            ],
                        },
                    ],
                },
                text: {
                    value: `Batch export '${BATCH_EXPORT_NAME_SLACK}' failed: ${BATCH_EXPORT_ERROR_SLACK}`,
                },
            },
        },
    ],
}

export const getSubTemplate = (
    template: HogFunctionTemplateType,
    subTemplateId: HogFunctionSubTemplateIdType
): HogFunctionSubTemplateType | null => {
    return HOG_FUNCTION_SUB_TEMPLATES[subTemplateId].find((x) => x.template_id === template.id) || null
}

export const eventToHogFunctionContextId = (event: string | undefined): HogFunctionConfigurationContextId => {
    switch (event) {
        case '$error_tracking_issue_created':
        case '$error_tracking_issue_reopened':
        case '$error_tracking_issue_spiking':
            return 'error-tracking'
        case '$insight_alert_firing':
            return 'insight-alerts'
        case '$experiment_metric_significant':
            return 'experiment-alerts'
        case '$activity_log_entry_created':
            return 'activity-log'
        case '$discussion_mention_created':
            return 'discussion-mention'
        case '$logs_alert_firing':
        case '$logs_alert_resolved':
        case '$logs_alert_auto_disabled':
        case '$logs_alert_errored':
            return 'logs-alerting'
        case '$health_check_issue_firing':
        case '$health_check_issue_resolved':
            return 'health-alerts'
        case '$batch_export_run_failed':
            return 'batch-export-alerts'
        default:
            return 'standard'
    }
}
