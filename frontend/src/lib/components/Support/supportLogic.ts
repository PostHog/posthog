import { MakeLogicType, actions, connect, kea, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import type { DeepPartial, DeepPartialMap, FieldName, ValidationErrorType } from 'kea-forms'
import posthog from 'posthog-js'

import { LemonSelectOptions } from '@posthog/lemon-ui'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { preflightLogic } from 'lib/logic/preflightLogic'
import { uuid } from 'lib/utils/dom'
import { billingLogic } from 'scenes/billing/billingLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import {
    AvailableFeature,
    BillingPlan,
    OrganizationBasicType,
    Region,
    SidePanelTab,
    StartupProgramLabel,
    TeamPublicType,
    UserType,
} from '~/types'

import type { BillingType, PreflightStatus } from '../../../types'
import type { FeatureFlagsSet } from '../../logic/featureFlagLogic'
import { parseExceptionEvent } from './exceptionUtils'
import { openSupportModal } from './SupportModal'

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
// internal http://go/session/ golink to make that explicit.
function getSessionReplayLink(): string {
    const replayUrl = posthog.get_session_replay_url?.({ withTimestamp: true, timestampLookBack: 30 })
    if (!replayUrl) {
        return ''
    }
    return `\nSession: ${replayUrl.replace(window.location.origin + '/replay/', 'http://go/session/')}`
}

function getErrorTrackingLink(uuid?: string): string {
    const values = [
        {
            key: '$session_id',
            value: [posthog.get_session_id()],
            operator: 'exact',
            type: 'event',
        },
    ]

    if (uuid) {
        values.push({
            type: 'hogql',
            key: `uuid = '${uuid}'`,
            value: null,
        } as any)
    }

    const filterGroup = encodeURIComponent(
        JSON.stringify({
            type: 'AND',
            values: [
                {
                    type: 'AND',
                    values,
                },
            ],
        })
    )

    return `\nExceptions: https://us.posthog.com/project/2/error_tracking?filterGroup=${filterGroup}`
}

function getDjangoAdminLink(
    user: UserType | null,
    cloudRegion: Region | null | undefined,
    currentOrganization: OrganizationBasicType | null,
    currentTeam: TeamPublicType | null
): string {
    if (!user || !cloudRegion) {
        return ''
    }
    const link = `https://${cloudRegion.toLowerCase()}.posthog.com/admin/posthog/user/${user.id}/change/`
    return `\nAdmin (internal): ${link} (organization ID ${currentOrganization?.id}: ${currentOrganization?.name}, project ID ${currentTeam?.id}: ${currentTeam?.name})`
}

function getBillingAdminLink(currentOrganization: OrganizationBasicType | null): string {
    if (!currentOrganization) {
        return ''
    }
    return `\nBilling admin (internal): http://go/billing/${currentOrganization.id}`
}

const SUPPORT_TICKET_KIND_TO_TITLE: Record<SupportTicketKind, string> = {
    support: 'Contact support',
    feedback: 'Give feedback',
    bug: 'Report a bug',
}

// The conversations extension loads lazily; poll briefly before deciding how to route so a fast
// submit right after page load doesn't miss it and fall back to Zendesk. Resolves as soon as it's
// available, or after the timeout.
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

const SUPPORT_TICKET_CUSTOM_FIELD_IDENTIFIERS = {
    severity: 22084126888475,
    distinct_id: 22129191462555,
    target_area: 27242745654043,
    organization_id: 27031528411291,
    support_type: 26073267652251,
    account_owner: 37742340880411,
    exception_event: 39967113285659,
} as const

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
    tags?: string[]
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface supportLogicValues {
    billing: BillingType | null // billingLogic
    featureFlags: FeatureFlagsSet // featureFlagLogic
    isCurrentOrganizationNew: boolean // organizationLogic
    preflight: PreflightStatus | null // preflightLogic
    sidePanelAvailable: boolean // sidePanelStateLogic
    hasAvailableFeature: (feature: AvailableFeature, currentUsage?: number | undefined) => boolean // userLogic
    user: UserType | null // userLogic
    conversationsFlagEnabled: boolean
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
    ensureZendeskOrganization: () => {
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
        conversationsFlagEnabled: (featureFlags: FeatureFlagsSet) => boolean
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
            preflightLogic,
            ['preflight'],
            userLogic,
            ['hasAvailableFeature'],
            billingLogic,
            ['billing'],
            organizationLogic,
            ['isCurrentOrganizationNew'],
            sidePanelStateLogic,
            ['sidePanelAvailable'],
            featureFlagLogic,
            ['featureFlags'],
        ],
        actions: [sidePanelStateLogic, ['openSidePanel', 'setSidePanelOptions']],
    })),
    actions(() => ({
        closeSupportForm: true,
        openSupportForm: (values: Partial<SupportFormFields> & { target?: 'modal' | 'sidePanel' }) => values,
        submitSupportTicket: (form: SupportFormFields) => form,
        ensureZendeskOrganization: true,
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
            errors: ({ name, email, message, kind, target_area, severity_level }) => {
                // Conversations tickets are just a message, like the side panel composer — the
                // triage fields only exist on the Zendesk form
                const requiresTriageFields = !values.conversationsFlagEnabled
                return {
                    name: !values.user && !name ? 'Please enter your name' : undefined,
                    email: !values.user && !email ? 'Please enter your email' : undefined,
                    message: !message ? 'Please enter a message' : undefined,
                    kind: requiresTriageFields && !kind ? 'Please choose' : undefined,
                    severity_level: requiresTriageFields && !severity_level ? 'Please choose' : undefined,
                    target_area: requiresTriageFields && !target_area ? 'Please choose' : undefined,
                }
            },
            submit: async (formValues) => {
                // name must be present for zendesk to accept the ticket
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
        conversationsFlagEnabled: [
            (s) => [s.featureFlags],
            (featureFlags: FeatureFlagsSet): boolean => !!featureFlags[FEATURE_FLAGS.PRODUCT_SUPPORT_SIDE_PANEL],
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
            const { name, email, kind, target_area, severity_level, message, exception_event, tags } = formValues

            // Conversations is where support is headed, so wait for the extension rather than racing
            // it to the (temporary) Zendesk fallback
            if (values.conversationsFlagEnabled && (await waitForConversations())) {
                try {
                    const response = await posthog.conversations!.sendMessage(
                        appendExceptionToMessage(message, exception_event),
                        { name: name || undefined, email: email || undefined },
                        true // every form submission starts a new ticket
                    )
                    if (response) {
                        // No support_ticket capture here: the backend fires $conversation_ticket_created
                        // for every new ticket, so a client-side event would double-count
                        actions.setLastSubmittedTicketId(response.ticket_id)
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
                        return
                    }
                    // null means the extension declined to send (not available) — nothing left the
                    // browser, so falling through to Zendesk cannot double-file the ticket
                } catch (e) {
                    // The request may have reached the server even though the response failed, so
                    // don't fall back to Zendesk here — that could file the ticket twice
                    posthog.captureException(e)
                    lemonToast.error("Oops, the message couldn't be sent. Please try again in a moment.", {
                        hideButton: true,
                    })
                    return
                }
            }

            // Fallback path: conversations flag off, or the extension never loaded. Tag flag-on
            // fallbacks so the (rare) volume is visible while Zendesk is being retired.
            const conversationsFallback = values.conversationsFlagEnabled
            const zendesk_ticket_uuid = uuid()
            const subject =
                SUPPORT_KIND_TO_SUBJECT[kind ?? 'support'] +
                ': ' +
                (target_area
                    ? (getLabelBasedOnTargetArea(target_area) ?? `${target_area} (feature preview)`)
                    : 'General') +
                ' (' +
                zendesk_ticket_uuid +
                ')'
            const cloudRegion = preflightLogic.values.preflight?.region

            const billing = billingLogic.values.billing
            const billingPlan = billingLogic.values.billingPlan

            let planLevelTag = 'plan_free'

            const knownEnterpriseOrgIds = ['018713f3-8d56-0000-32fa-75ce97e6662f']
            const isKnownEnterpriseOrg = knownEnterpriseOrgIds.includes(userLogic?.values?.user?.organization?.id || '')

            const isNewOrganization = values.isCurrentOrganizationNew

            const hasBoostTrial = billing?.trial?.status === 'active' && billing.trial?.target === 'boost'
            const hasScaleTrial = billing?.trial?.status === 'active' && billing.trial?.target === 'scale'
            const hasEnterpriseTrial = billing?.trial?.status === 'active' && billing.trial?.target === 'enterprise'

            if (isKnownEnterpriseOrg || hasEnterpriseTrial || billingPlan === BillingPlan.Enterprise) {
                planLevelTag = 'plan_enterprise'
            } else if (isNewOrganization) {
                planLevelTag = 'plan_onboarding'
            } else if (hasScaleTrial) {
                planLevelTag = 'plan_scale'
            } else if (hasBoostTrial) {
                planLevelTag = 'plan_boost'
            } else if (billingPlan) {
                switch (billingPlan) {
                    case BillingPlan.Scale:
                        planLevelTag = 'plan_scale'
                        break
                    case BillingPlan.Boost:
                        planLevelTag = 'plan_boost'
                        break
                    case BillingPlan.Teams:
                        planLevelTag = 'plan_teams_legacy'
                        break
                    case BillingPlan.Paid:
                        const projectedAmount = parseFloat(billing?.projected_total_amount_usd_with_limit || '0')
                        const shouldMarkAsFree = projectedAmount === 0

                        planLevelTag = shouldMarkAsFree ? 'plan_pay-as-you-go_free' : 'plan_pay-as-you-go_paying'
                        break
                    case BillingPlan.Free:
                        planLevelTag = 'plan_free'
                        break
                }
            }

            const startupProgramLabel = billing?.startup_program_label
            if (startupProgramLabel === StartupProgramLabel.YC) {
                planLevelTag = 'plan_yc'
            } else if (startupProgramLabel === StartupProgramLabel.Startup) {
                planLevelTag = 'plan_startup'
            }

            const { accountOwner } = billingLogic.values

            const ownerName = accountOwner?.name?.toLowerCase().replace(/[^a-z0-9]/g, '_') || 'unassigned'
            const accountOwnerTag = `owner_${ownerName}`

            const payload = {
                request: {
                    requester: { name: name, email: email },
                    subject: subject,
                    tags: [
                        planLevelTag,
                        accountOwnerTag,
                        ...(conversationsFallback ? ['conversations_fallback'] : []),
                        ...(tags || []),
                    ],
                    custom_fields: [
                        {
                            id: SUPPORT_TICKET_CUSTOM_FIELD_IDENTIFIERS.severity,
                            value: severity_level,
                        },
                        {
                            id: SUPPORT_TICKET_CUSTOM_FIELD_IDENTIFIERS.distinct_id,
                            value: posthog.get_distinct_id(),
                        },
                        {
                            id: SUPPORT_TICKET_CUSTOM_FIELD_IDENTIFIERS.target_area,
                            value: target_area ?? '',
                        },
                        {
                            id: SUPPORT_TICKET_CUSTOM_FIELD_IDENTIFIERS.organization_id,
                            value: userLogic?.values?.user?.organization?.id ?? '',
                        },
                        {
                            id: SUPPORT_TICKET_CUSTOM_FIELD_IDENTIFIERS.support_type,
                            value: values.hasAvailableFeature(AvailableFeature.PRIORITY_SUPPORT)
                                ? 'priority_support'
                                : values.hasAvailableFeature(AvailableFeature.EMAIL_SUPPORT)
                                  ? 'email_support'
                                  : 'free_support',
                        },
                        {
                            id: SUPPORT_TICKET_CUSTOM_FIELD_IDENTIFIERS.account_owner,
                            value: accountOwner?.name || 'unassigned',
                        },
                        {
                            id: SUPPORT_TICKET_CUSTOM_FIELD_IDENTIFIERS.exception_event,
                            value: exception_event ? parseExceptionEvent(exception_event) : '',
                        },
                    ],
                    comment: {
                        body:
                            message +
                            `\n\n-----` +
                            `\nKind: ${kind ?? 'support'}` +
                            `\nTarget area: ${target_area ?? 'General'}` +
                            `\nReport event: http://go/ticketByUUID/${zendesk_ticket_uuid}` +
                            getSessionReplayLink() +
                            getErrorTrackingLink(exception_event?.uuid) +
                            getCurrentLocationLink() +
                            getDjangoAdminLink(
                                userLogic.values.user,
                                cloudRegion,
                                organizationLogic.values.currentOrganization,
                                teamLogic.values.currentTeam
                            ) +
                            (target_area === 'billing' || target_area === 'login' || target_area === 'onboarding'
                                ? getBillingAdminLink(organizationLogic.values.currentOrganization)
                                : '') +
                            (cloudRegion && teamLogic.values.currentTeam
                                ? '\nPersons-on-events mode for project: ' +
                                  (teamLogic.values.currentTeam.modifiers?.personsOnEventsMode ??
                                      teamLogic.values.currentTeam.default_modifiers?.personsOnEventsMode ??
                                      'unknown')
                                : ''),
                    },
                },
            }

            try {
                const zendeskRequestBody = JSON.stringify(payload, undefined, 4)

                // First attempt with standard fetch (unchanged from original)
                const response = await fetch('https://posthoghelp.zendesk.com/api/v2/requests.json', {
                    method: 'POST',
                    body: zendeskRequestBody,
                    headers: { 'Content-Type': 'application/json' },
                })

                // If the fetch request fails, try the Beacon API as a fallback
                if (!response.ok) {
                    console.warn('Fetch attempt to submit support ticket failed, trying Beacon API as fallback')

                    // Detect Firefox
                    const isFirefox = navigator.userAgent.toLowerCase().indexOf('firefox') > -1

                    // Try Beacon API
                    const beaconSuccess = navigator.sendBeacon(
                        'https://posthoghelp.zendesk.com/api/v2/requests.json',
                        zendeskRequestBody
                    )

                    if (beaconSuccess) {
                        // Track success
                        const properties = {
                            zendesk_ticket_uuid,
                            kind,
                            target_area,
                            message,
                            submission_method: 'beacon',
                            browser: isFirefox ? 'firefox' : 'other',
                        }
                        posthog.capture('support_ticket', properties)
                        lemonToast.success(
                            "Got the message! If we have follow-up information for you, we'll reply via email."
                        )
                        // Only close and reset the form on success
                        actions.closeSupportForm()
                        actions.resetSendSupportRequest()
                        return
                    }

                    // If both fetch and beacon fail, show the original error message
                    const error = new Error(`There was an error creating the support ticket with zendesk.`)
                    const extra: Record<string, any> = { zendeskBody: zendeskRequestBody }
                    Object.entries(payload).forEach(([key, value]) => {
                        extra[`payload_${key}`] = value
                    })
                    const body = await response.text()
                    const contexts = {
                        response: {
                            status_code: response.status,
                            data: body,
                            body_size: body?.length,
                        },
                    }
                    posthog.captureException(error, {
                        ...extra,
                        ...contexts,
                    })
                    lemonToast.error(
                        `Oops, the message couldn't be sent. Please change your browser's privacy level to the standard or default level, then try again. (E.g. In Firefox: Settings > Privacy & Security > Standard)`,
                        { hideButton: true }
                    )
                    // Don't close the form or reset the data so user can try again
                    return
                }

                const json = await response.json()

                const zendesk_ticket_id = json.request.id
                const zendesk_ticket_link = `https://posthoghelp.zendesk.com/agent/tickets/${zendesk_ticket_id}`
                const properties = {
                    zendesk_ticket_uuid,
                    kind,
                    target_area,
                    message,
                    zendesk_ticket_id,
                    zendesk_ticket_link,
                }
                posthog.capture('support_ticket', properties)
                lemonToast.success("Got the message! If we have follow-up information for you, we'll reply via email.")

                actions.ensureZendeskOrganization()
                actions.setLastSubmittedTicketId(zendesk_ticket_id)

                // Only close and reset the form on success
                actions.closeSupportForm()
                actions.resetSendSupportRequest()
            } catch (e) {
                posthog.captureException(e)

                // More helpful error message
                // Use the same error message regardless of browser
                lemonToast.error(
                    `Oops, the message couldn't be sent. Please change your browser's privacy level to the standard or default level, then try again. (E.g. In Firefox: Settings > Privacy & Security > Standard)`,
                    { hideButton: true }
                )
                // Don't close the form or reset the data so user can try again
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

        ensureZendeskOrganization: async () => {
            try {
                const currentOrganization = organizationLogic.values.currentOrganization

                if (!currentOrganization?.id || !currentOrganization?.name) {
                    return
                }

                await api.create('/api/support/ensure-zendesk-organization', {
                    organization_id: currentOrganization.id,
                    organization_name: currentOrganization.name,
                })
            } catch (error) {
                posthog.captureException(error, {
                    context: 'zendesk_organization_creation',
                    organization_id: organizationLogic.values.currentOrganization?.id,
                    organization_name: organizationLogic.values.currentOrganization?.name,
                    error_message: error instanceof Error ? error.message : String(error),
                    error_status: error && typeof error === 'object' && 'status' in error ? error.status : undefined,
                })
            }
        },
    })),
])
