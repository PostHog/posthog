import { MakeLogicType, actions, connect, kea, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import type { DeepPartial, DeepPartialMap, FieldName, ValidationErrorType } from 'kea-forms'
import posthog from 'posthog-js'

import { LemonSelectOptions } from '@posthog/lemon-ui'

import { EMAIL_SUPPORT_BUTTON, lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { billingLogic } from 'scenes/billing/billingLogic'
import { userLogic } from 'scenes/userLogic'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import {
    BillingPlan,
    BillingPlanType,
    OrganizationBasicType,
    Region,
    SidePanelTab,
    TeamPublicType,
    UserType,
} from '~/types'

import type { BillingType } from '../../../types'
import { parseExceptionEvent } from './exceptionUtils'
import { openSupportModal } from './SupportModal'
import { getSupportResponseTime } from './supportResponseTime'

export function getPublicSupportSnippet(
    cloudRegion: Region | null | undefined,
    currentOrganization: OrganizationBasicType | null,
    currentTeam: TeamPublicType | null,
    includeCurrentLocation = true
): string {
    if (!cloudRegion) {
        // we don't call this without region being available, so we return some value so we can see errors in visual regression tests
        return '🚫'
    }
    return (
        (includeCurrentLocation ? getCurrentLocationLink() : '') +
        getSessionReplayLink() +
        `\nAdmin (internal): http://go/adminOrg${cloudRegion}/${currentOrganization?.id} (project ID ${currentTeam?.id})`
    ).trimStart()
}

function getCurrentLocationLink(): string {
    const cleanedCurrentUrl = window.location.href.replace(/panel=support[^&]*(&)?/, '').replace(/#$/, '')
    return `\nLocation: ${cleanedCurrentUrl}`
}

// The recording lives in PostHog's own telemetry project, which the reporting user is not a member
// of, so this link is for PostHog staff triaging the ticket/issue — never the user. We rewrite to the
// internal http://go/session/ golink to make that explicit. posthog-js returns a project-scoped path
// (`/project/<token>/replay/<id>`), so pull the session id out of the `/replay/` segment rather than
// assuming the URL starts with the current origin.
function getSessionReplayLink(): string {
    const replayUrl = posthog.get_session_replay_url?.({ withTimestamp: true, timestampLookBack: 30 })
    if (!replayUrl) {
        return ''
    }
    const match = replayUrl.match(/\/replay\/([^/?#]+)([?#].*)?$/)
    if (!match) {
        return ''
    }
    const [, sessionId, queryAndHash] = match
    return `\nSession: http://go/session/${sessionId}${queryAndHash ?? ''}`
}

const SUPPORT_TICKET_KIND_TO_TITLE: Record<SupportTicketKind, string> = {
    support: 'Contact support',
    feedback: 'Give feedback',
    bug: 'Report a bug',
}

// The conversations extension loads lazily; poll briefly before sending so a fast submit right
// after page load doesn't miss it. Resolves as soon as it's available, or after the timeout.
async function waitForConversations(timeoutMs = 5000): Promise<boolean> {
    const intervalMs = 250
    for (let waited = 0; waited < timeoutMs; waited += intervalMs) {
        if (posthog.conversations?.isAvailable()) {
            return true
        }
        await new Promise((resolve) => setTimeout(resolve, intervalMs))
    }
    return !!posthog.conversations?.isAvailable()
}

// Mirrors the widget message serializer cap (WidgetMessageSerializer.message). Support submits post
// through posthog.conversations.sendMessage (the widget endpoint), so guard against the same cap.
export const CONVERSATIONS_MESSAGE_MAX_LENGTH = 10000

// Shared over-limit guard for the conversations composer surfaces (support form + side panel). Shows
// an error toast and returns true when the message exceeds the widget cap, so callers bail before
// hitting the endpoint and surfacing only a generic send-failure toast.
export function warnIfMessageTooLong(message: string): boolean {
    if (message.length > CONVERSATIONS_MESSAGE_MAX_LENGTH) {
        lemonToast.error(
            `Your message is too long (max ${CONVERSATIONS_MESSAGE_MAX_LENGTH.toLocaleString()} characters). Please shorten it or send it in multiple messages.`
        )
        return true
    }
    return false
}

// Conversations tickets carry just the user's message (like the side panel composer), but for bug
// reports we still fold the exception in so it survives on email-channel tickets and when the
// agent's session-scoped exceptions panel can't resolve it. Mirrors how feature-preview feedback
// names its feature in the message body.
export function appendExceptionToMessage(message: string, exception_event?: SupportTicketExceptionEvent): string {
    if (!exception_event) {
        return message
    }
    return `${message}\n\n-----\nException: ${parseExceptionEvent(exception_event)}`
}

const TARGET_AREA_TO_NAME_GENERAL = [
    {
        value: 'login',
        'data-attr': `support-form-target-area-login`,
        label: 'Authentication (incl. login, sign-up, invites)',
    },
    {
        value: 'analytics_platform',
        'data-attr': `support-form-target-area-analytics_platform`,
        label: 'Analytics features (incl. alerts, subscriptions, exports, etc.)',
    },
    {
        value: 'billing',
        'data-attr': `support-form-target-area-billing`,
        label: 'Billing',
    },
    {
        value: 'cohorts',
        'data-attr': `support-form-target-area-cohorts`,
        label: 'Cohorts',
    },
    {
        value: 'data_ingestion',
        'data-attr': `support-form-target-area-data_ingestion`,
        label: 'Data ingestion',
    },
    {
        value: 'health_overview',
        'data-attr': `support-form-target-area-health_overview`,
        label: 'Health overview',
    },
    {
        value: 'data_management',
        'data-attr': `support-form-target-area-data_management`,
        label: 'Data management (incl. events, actions, properties)',
    },
    {
        value: 'mobile',
        'data-attr': `support-form-target-area-mobile`,
        label: 'Mobile',
    },
    {
        value: 'notebooks',
        'data-attr': `support-form-target-area-notebooks`,
        label: 'Notebooks',
    },
    {
        value: 'onboarding',
        'data-attr': `support-form-target-area-onboarding`,
        label: 'Onboarding',
    },
    {
        value: 'platform_addons',
        'data-attr': `support-form-target-area-platform_addons`,
        label: 'Platform addons',
    },
    {
        value: 'sdk',
        'data-attr': `support-form-target-area-onboarding`,
        label: 'SDK / Implementation',
    },
    {
        value: 'setup-wizard',
        'data-attr': `support-form-target-area-setup-wizard`,
        label: 'Wizard',
    },
] as const satisfies LemonSelectOptions<string>

const TARGET_AREA_TO_NAME_PRODUCTS = [
    {
        value: 'ai_gateway',
        'data-attr': `support-form-target-area-ai_gateway`,
        label: 'AI gateway',
    },
    {
        value: 'llm-analytics',
        'data-attr': `support-form-target-area-llm-analytics`,
        label: 'AI observability',
    },
    {
        value: 'apps',
        'data-attr': `support-form-target-area-apps`,
        label: 'Apps (incl. integrations, plugins, webhooks, and custom apps)',
    },
    {
        value: 'batch_exports',
        'data-attr': `support-form-target-area-batch_exports`,
        label: 'Destinations (batch exports)',
    },
    {
        value: 'cdp_destinations',
        'data-attr': `support-form-target-area-cdp_destinations`,
        label: 'Destinations (real-time)',
    },
    {
        value: 'data_modeling',
        'data-attr': `support-form-target-area-data_modeling`,
        label: 'Data modeling (views, matviews, endpoints)',
    },
    {
        value: 'data_warehouse',
        'data-attr': `support-form-target-area-data_warehouse`,
        label: 'Data warehouse (sources)',
    },
    {
        value: 'error_tracking',
        'data-attr': `support-form-target-area-error_tracking`,
        label: 'Error tracking',
    },
    {
        value: 'experiments',
        'data-attr': `support-form-target-area-experiments`,
        label: 'Experiments',
    },
    {
        value: 'feature_flags',
        'data-attr': `support-form-target-area-feature_flags`,
        label: 'Feature flags',
    },
    {
        value: 'group_analytics',
        'data-attr': `support-form-target-area-group-analytics`,
        label: 'Group analytics',
    },
    {
        value: 'customer_analytics',
        'data-attr': `support-form-target-area-customer-analytics`,
        label: 'Customer analytics',
    },
    {
        value: 'heatmaps',
        'data-attr': `support-form-target-area-heatmaps`,
        label: 'Heatmaps',
    },
    {
        value: 'logs',
        'data-attr': `support-form-target-area-logs`,
        label: 'Logs',
    },
    {
        value: 'posthog-ai',
        'data-attr': `support-form-target-area-posthog-ai`,
        label: 'PostHog AI',
    },
    {
        value: 'posthog-mcp',
        'data-attr': `support-form-target-area-posthog-mcp`,
        label: 'PostHog MCP',
    },
    {
        value: 'analytics',
        'data-attr': `support-form-target-area-analytics`,
        label: 'Product analytics (incl. insights, dashboards, etc.)',
    },
    {
        value: 'revenue_analytics',
        'data-attr': `support-form-target-area-revenue-analytics`,
        label: 'Revenue analytics',
    },
    {
        value: 'session_replay',
        'data-attr': `support-form-target-area-session_replay`,
        label: 'Session replay (incl. recordings)',
    },
    {
        value: 'signals',
        'data-attr': `support-form-target-area-signals`,
        label: 'Inbox',
    },
    {
        value: 'slack',
        'data-attr': `support-form-target-area-slack`,
        label: 'Slack app',
    },
    {
        value: 'surveys',
        'data-attr': `support-form-target-area-surveys`,
        label: 'Surveys',
    },
    {
        value: 'toolbar',
        'data-attr': `support-form-target-area-toolbar`,
        label: 'Toolbar',
    },
    {
        value: 'web_analytics',
        'data-attr': `support-form-target-area-web_analytics`,
        label: 'Web analytics',
    },
    {
        value: 'workflows',
        'data-attr': `support-form-target-area-workflows`,
        label: 'Workflows / Messaging',
    },
] as const satisfies LemonSelectOptions<string>

export const TARGET_AREA_TO_NAME = [
    { title: 'General', options: TARGET_AREA_TO_NAME_GENERAL },
    { title: 'Individual product', options: TARGET_AREA_TO_NAME_PRODUCTS },
]

// `key` is the label (not the value) so the searchable input shows readable text on edit, not the raw target_area
export const TARGET_AREA_OPTIONS: { key: string; label: string; value: string }[] = TARGET_AREA_TO_NAME.flatMap(
    (group) => group.options.map((option) => ({ key: option.label, label: option.label, value: option.value }))
)

export const SEVERITY_LEVEL_TO_NAME = {
    critical: 'Outage, data loss, or data breach',
    high: 'Feature is not working at all',
    medium: 'Feature not working as expected',
    low: 'Question or feature request',
}

export const SUPPORT_KIND_TO_SUBJECT = {
    bug: 'Bug Report',
    feedback: 'Feedback',
    support: 'Support Ticket',
}

export type SupportTicketTargetArea =
    | (typeof TARGET_AREA_TO_NAME_GENERAL)[number]['value']
    | (typeof TARGET_AREA_TO_NAME_PRODUCTS)[number]['value']
export type SupportTicketSeverityLevel = keyof typeof SEVERITY_LEVEL_TO_NAME
export type SupportTicketKind = keyof typeof SUPPORT_KIND_TO_SUBJECT

export type SupportTicketExceptionEvent = { uuid: string; event: string; properties?: Record<string, any> }

export const getLabelBasedOnTargetArea = (target_area: SupportTicketTargetArea): null | string => {
    for (const category of TARGET_AREA_TO_NAME) {
        for (const option of category.options) {
            if (option.value === target_area) {
                return option.label
            }
        }
    }
    return null // Return null if the value is not found
}

export const URL_PATH_TO_TARGET_AREA: Record<string, SupportTicketTargetArea> = {
    'ai-gateway': 'ai_gateway',
    insights: 'analytics',
    recordings: 'session_replay',
    replay: 'session_replay',
    dashboard: 'analytics',
    feature_flags: 'feature_flags',
    experiments: 'experiments',
    'web-performance': 'session_replay',
    events: 'analytics',
    'data-management': 'data_management',
    cohorts: 'cohorts',
    annotations: 'analytics',
    persons: 'analytics',
    groups: 'analytics',
    heatmaps: 'heatmaps',
    toolbar: 'toolbar',
    warehouse: 'data_warehouse',
    surveys: 'surveys',
    web: 'web_analytics',
    destination: 'cdp_destinations',
    destinations: 'cdp_destinations',
    transformation: 'cdp_destinations',
    transformations: 'cdp_destinations',
    source: 'data_warehouse',
    sources: 'data_warehouse',
    workflows: 'workflows',
    billing: 'billing',
    logs: 'logs',
    inbox: 'signals',
}

export const SUPPORT_TICKET_TEMPLATES = {
    bug: 'Please describe the bug you saw, and how to reproduce it.\n\nIf the bug appeared on a specific insight or dashboard, please include a link to it.',
    feedback:
        "If your request is due to a problem, please describe the problem as best you can.\n\nPlease also describe the solution you'd like to see, and any alternatives you considered.\n\nYou can add images below to help illustrate your request, if needed!",
    support:
        "Please explain as fully as possible what you're aiming to do, and what you'd like help with.\n\nIf your question involves an existing insight or dashboard, please include a link to it.",
}

export function getURLPathToTargetArea(pathname: string): SupportTicketTargetArea | null {
    const pathParts = pathname.split('/')

    if (pathname.includes('pipeline/destinations/') && !pathname.includes('/hog-')) {
        return 'batch_exports'
    }

    for (const part of pathParts) {
        if (URL_PATH_TO_TARGET_AREA[part]) {
            return URL_PATH_TO_TARGET_AREA[part]
        }
    }

    return null
}

export type SupportFormLogicProps = {
    onClose?: () => void
}

export type SupportFormFields = {
    name: string
    email: string
    kind: SupportTicketKind
    target_area: SupportTicketTargetArea | null
    severity_level: SupportTicketSeverityLevel | null
    message: string
    exception_event?: SupportTicketExceptionEvent
    isEmailFormOpen?: boolean | 'true' | 'false'
    // Set when the ticket originates from a PostHog AI (/ticket, feedback) handover, so the created
    // ticket can be attributed back to the conversation regardless of which submit path files it.
    ai_conversation_id?: string | null
    ai_trace_id?: string | null
    ai_feedback_rating?: string | null
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface supportLogicValues {
    billing: BillingType | null // billingLogic
    billingPlan: BillingPlan | null // billingLogic
    supportPlans: BillingPlanType[] // billingLogic
    sidePanelAvailable: boolean // sidePanelStateLogic
    user: UserType | null // userLogic
    isEmailFormOpen: boolean
    isSendSupportRequestSubmitting: boolean
    isSendSupportRequestValid: boolean
    isSupportFormOpen: boolean
    lastSubmittedTicketId: string | null
    pendingViewTicket: {
        created_at: string
        id: string
        status: string
    } | null
    sendSupportRequest: SupportFormFields
    sendSupportRequestAllErrors: Record<string, any>
    sendSupportRequestChanged: boolean
    sendSupportRequestErrors: DeepPartialMap<SupportFormFields, ValidationErrorType>
    sendSupportRequestHasErrors: boolean
    sendSupportRequestManualErrors: Record<string, any>
    sendSupportRequestTouched: boolean
    sendSupportRequestTouches: Record<string, boolean>
    sendSupportRequestValidationErrors: DeepPartialMap<SupportFormFields, ValidationErrorType>
    showSendSupportRequestErrors: boolean
    supportResponseTime: string | null
    targetArea: SupportTicketTargetArea | null
    title: string
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface supportLogicActions {
    openSidePanel: (
        tab: SidePanelTab,
        options?: string | undefined
    ) => {
        options: string | undefined
        tab: SidePanelTab
    } // sidePanelStateLogic
    setSidePanelOptions: (options: string | null) => {
        options: string | null
    } // sidePanelStateLogic
    clearPendingViewTicket: () => {
        value: true
    }
    closeEmailForm: () => {
        value: true
    }
    closeSupportForm: () => {
        value: true
    }
    openEmailForm: () => {
        value: true
    }
    openSupportForm: (
        values: Partial<SupportFormFields> & {
            target?: 'modal' | 'sidePanel'
        }
    ) => Partial<SupportFormFields> & {
        target?: 'modal' | 'sidePanel' | undefined
    }
    resetSendSupportRequest: (values?: SupportFormFields) => {
        values?: SupportFormFields
    }
    setLastSubmittedTicketId: (ticketId: string | null) => {
        ticketId: string | null
    }
    setSendSupportRequestManualErrors: (errors: Record<string, any>) => {
        errors: Record<string, any>
    }
    setSendSupportRequestValue: (
        key: FieldName,
        value: any
    ) => {
        name: FieldName
        value: any
    }
    setSendSupportRequestValues: (values: DeepPartial<SupportFormFields>) => {
        values: DeepPartial<SupportFormFields>
    }
    submitSendSupportRequest: () => {
        value: boolean
    }
    submitSendSupportRequestFailure: (
        error: Error,
        errors: Record<string, any>
    ) => {
        error: Error
        errors: Record<string, any>
    }
    submitSendSupportRequestRequest: (sendSupportRequest: SupportFormFields) => {
        sendSupportRequest: SupportFormFields
    }
    submitSendSupportRequestSuccess: (sendSupportRequest: SupportFormFields) => {
        sendSupportRequest: SupportFormFields
    }
    submitSupportTicket: (form: SupportFormFields) => SupportFormFields
    touchSendSupportRequestField: (key: string) => {
        key: string
    }
    updateUrlParams: () => {
        value: true
    }
    viewConversationsTicket: (ticket: { created_at: string; id: string; status: string }) => {
        ticket: {
            created_at: string
            id: string
            status: string
        }
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface supportLogicMeta {
    __keaTypeGenInternalSelectorTypes: {
        title: (arg: SupportFormFields) => string
        targetArea: (sendSupportRequest: SupportFormFields) => SupportTicketTargetArea | null
        supportResponseTime: (
            billing: BillingType | null,
            billingPlan: BillingPlan | null,
            supportPlans: BillingPlanType[],
            user: UserType | null
        ) => string | null
    }
}

export type supportLogicType = MakeLogicType<
    supportLogicValues,
    supportLogicActions,
    SupportFormLogicProps,
    supportLogicMeta
>

export const supportLogic = kea<supportLogicType>([
    props({} as SupportFormLogicProps),
    path(['lib', 'components', 'support', 'supportLogic']),
    connect(() => ({
        values: [
            userLogic,
            ['user'],
            billingLogic,
            ['billing', 'billingPlan', 'supportPlans'],
            sidePanelStateLogic,
            ['sidePanelAvailable'],
        ],
        actions: [sidePanelStateLogic, ['openSidePanel', 'setSidePanelOptions']],
    })),
    actions(() => ({
        closeSupportForm: true,
        openSupportForm: (values: Partial<SupportFormFields> & { target?: 'modal' | 'sidePanel' }) => values,
        submitSupportTicket: (form: SupportFormFields) => form,
        updateUrlParams: true,
        openEmailForm: true,
        closeEmailForm: true,
        setLastSubmittedTicketId: (ticketId: string | null) => ({ ticketId }),
        viewConversationsTicket: (ticket: { id: string; status: string; created_at: string }) => ({ ticket }),
        clearPendingViewTicket: true,
    })),
    reducers(() => ({
        isSupportFormOpen: [
            false,
            {
                openSupportForm: () => true,
                closeSupportForm: () => false,
            },
        ],
        isEmailFormOpen: [
            false,
            {
                openEmailForm: () => true,
                closeEmailForm: () => false,
            },
        ],
        lastSubmittedTicketId: [
            null as string | null,
            {
                setLastSubmittedTicketId: (_, { ticketId }) => ticketId,
                openSupportForm: () => null, // Reset when opening a new form
            },
        ],
        // A conversations ticket the side panel should open on when it next renders — set when the
        // user clicks "View" on a submission toast, consumed by sidepanelTicketsLogic
        pendingViewTicket: [
            null as { id: string; status: string; created_at: string } | null,
            {
                viewConversationsTicket: (_, { ticket }) => ticket,
                clearPendingViewTicket: () => null,
            },
        ],
    })),
    forms(({ values }) => ({
        sendSupportRequest: {
            defaults: {
                name: '',
                email: '',
                kind: 'support',
                severity_level: null,
                target_area: null,
                message: '',
            } as SupportFormFields,
            errors: ({ name, email, message }) => {
                return {
                    name: !values.user && !name ? 'Please enter your name' : undefined,
                    email: !values.user && !email ? 'Please enter your email' : undefined,
                    message: !message ? 'Please enter a message' : undefined,
                }
            },
            submit: async (formValues) => {
                formValues.name = values.user?.first_name ?? formValues.name ?? 'name not set'
                formValues.email = values.user?.email ?? formValues.email ?? ''
                await supportLogic.asyncActions.submitSupportTicket(formValues)
            },
        },
    })),
    selectors({
        title: [
            (s) => [s.sendSupportRequest ?? null],
            (sendSupportRequest: SupportFormFields) =>
                sendSupportRequest.kind
                    ? SUPPORT_TICKET_KIND_TO_TITLE[sendSupportRequest.kind]
                    : 'Leave a message with PostHog',
        ],
        targetArea: [
            (s) => [s.sendSupportRequest],
            (sendSupportRequest: SupportFormFields) => sendSupportRequest.target_area,
        ],
        supportResponseTime: [
            (s) => [s.billing, s.billingPlan, s.supportPlans, s.user],
            (
                billing: BillingType | null,
                billingPlan: BillingPlan | null,
                supportPlans: BillingPlanType[],
                user: UserType | null
            ): string | null =>
                getSupportResponseTime({
                    billing,
                    billingPlan,
                    supportPlans,
                    organizationId: user?.organization?.id,
                }),
        ],
    }),
    listeners(({ actions, props, values }) => ({
        updateUrlParams: async () => {
            // Only include non-text fields in the URL parameters
            // This prevents focus loss when typing in text fields
            const panelOptions = [
                values.sendSupportRequest.kind ?? '',
                values.sendSupportRequest.target_area ?? '',
                values.sendSupportRequest.severity_level ?? '',
                values.isEmailFormOpen ?? 'false',
            ].join(':')

            if (panelOptions !== ':') {
                actions.setSidePanelOptions(panelOptions)
            }
        },
        openSupportForm: async ({
            name,
            email,
            isEmailFormOpen,
            kind,
            target_area,
            severity_level,
            message,
            exception_event,
            target,
        }: Partial<SupportFormFields> & { target?: 'modal' | 'sidePanel' }) => {
            let area = target_area ?? getURLPathToTargetArea(window.location.pathname)
            if (!userLogic.values.user) {
                area = 'login'
            }
            kind = kind ?? 'support'
            actions.resetSendSupportRequest({
                name: name ?? '',
                email: email ?? '',
                kind,
                target_area: area,
                severity_level: severity_level ?? null,
                message: message ?? values.sendSupportRequest.message ?? '',
                exception_event,
            })

            if (isEmailFormOpen === 'true' || isEmailFormOpen === true) {
                actions.openEmailForm()
            } else {
                actions.closeEmailForm()
            }

            const useSidePanel = target ? target === 'sidePanel' : values.sidePanelAvailable
            if (useSidePanel) {
                const panelOptions = [kind ?? '', area ?? ''].join(':')
                actions.openSidePanel(SidePanelTab.Support, panelOptions === ':' ? undefined : panelOptions)
            } else {
                openSupportModal()
            }

            actions.updateUrlParams()
        },
        submitSupportTicket: async (formValues: SupportFormFields) => {
            const { name, email, kind, target_area, message, exception_event } = formValues
            const { ai_conversation_id, ai_trace_id, ai_feedback_rating } = formValues

            // Attribute PostHog AI (/ticket, feedback) handovers to the conversation. The ticket id
            // only exists once the send resolves — capturing from here means it fires no matter which
            // caller triggered the submit, instead of relying on a component effect that races the
            // async conversations round-trip and silently drops the event.
            const captureAiSupportTicket = (ticketId: string | number): void => {
                if (!ai_conversation_id) {
                    return
                }
                posthog.capture('posthog_ai_support_ticket_created', {
                    $ai_conversation_id: ai_conversation_id,
                    $ai_session_id: ai_conversation_id,
                    $ai_trace_id: ai_trace_id ?? null,
                    $ai_support_ticket_id: String(ticketId),
                    ...(ai_feedback_rating ? { $ai_feedback_rating: ai_feedback_rating } : {}),
                })
            }

            const sendFailed = (error?: unknown): void => {
                posthog.capture('support ticket send failed', {
                    channel: 'conversations',
                    error: error !== undefined ? (error instanceof Error ? error.message : String(error)) : undefined,
                    kind,
                    target_area,
                    message_length: message?.length,
                    current_url_length: window.location.href.length,
                })
                lemonToast.error("Oops, the message couldn't be sent. Please try again in a moment.", {
                    button: EMAIL_SUPPORT_BUTTON,
                })
            }

            if (!(await waitForConversations())) {
                sendFailed()
                return
            }

            // Measure the full outgoing payload (message plus any appended exception) so the guard
            // matches what the widget endpoint actually receives and rejects
            const outgoingMessage = appendExceptionToMessage(message, exception_event)
            if (warnIfMessageTooLong(outgoingMessage)) {
                return
            }
            try {
                const response = await posthog.conversations!.sendMessage(
                    outgoingMessage,
                    { name: name || undefined, email: email || undefined },
                    true // every form submission starts a new ticket
                )
                if (!response) {
                    // The extension declined to send (e.g. it became unavailable between the wait
                    // above and this call) — nothing left the browser
                    sendFailed()
                    return
                }
                // No support_ticket capture here: the backend fires $conversation_ticket_created for
                // every new ticket, so a client-side event would double-count
                actions.setLastSubmittedTicketId(response.ticket_id)
                captureAiSupportTicket(response.ticket_id)
                lemonToast.success(
                    values.sidePanelAvailable
                        ? 'Got the message! You can view replies from our support engineers in the support panel.'
                        : "Got the message! Our support engineers will follow up by email if there's more to share.",
                    values.sidePanelAvailable
                        ? {
                              button: {
                                  label: 'View',
                                  action: () =>
                                      actions.viewConversationsTicket({
                                          id: response.ticket_id,
                                          status: response.ticket_status,
                                          created_at: response.created_at,
                                      }),
                              },
                          }
                        : undefined
                )
                actions.closeEmailForm()
                actions.closeSupportForm()
                actions.resetSendSupportRequest()
            } catch (e) {
                // The request may have reached the server even though the response failed, so don't
                // retry here — that could file the ticket twice
                posthog.captureException(e)
                sendFailed(e)
            }
        },

        viewConversationsTicket: () => {
            actions.openSidePanel(SidePanelTab.Support)
        },

        closeSupportForm: () => {
            // Form is only reset by explicit Cancel button or successful submission
            props.onClose?.()
        },

        setSendSupportRequestValue: ({ name }) => {
            // Only update URL params for non-text fields to prevent focus loss during typing
            if (name !== 'message' && name !== 'name' && name !== 'email') {
                actions.updateUrlParams()
            }
        },

    })),
])
