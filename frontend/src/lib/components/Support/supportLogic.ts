import { actions, connect, kea, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { urlToAction } from 'kea-router'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { uuid } from 'lib/utils'
import posthog from 'posthog-js'
import api from 'lib/api'
import { billingLogic } from 'scenes/billing/billingLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import {
    AvailableFeature,
    BillingPlan,
    OrganizationBasicType,
    Region,
    SidePanelTab,
    TeamPublicType,
    UserType,
} from '~/types'

import type { supportLogicType } from './supportLogicType'
import { openSupportModal } from './SupportModal'

export function getPublicSupportSnippet(
    cloudRegion: Region | null | undefined,
    currentOrganization: OrganizationBasicType | null,
    currentTeam: TeamPublicType | null,
    includeCurrentLocation = true
): string {
    if (!cloudRegion) {
        return ''
    }
    return (
        (includeCurrentLocation ? getCurrentLocationLink() : '') +
        getSessionReplayLink() +
        `\nAdmin: http://go/adminOrg${cloudRegion}/${currentOrganization?.id} (project ID ${currentTeam?.id})`
    ).trimStart()
}

function getCurrentLocationLink(): string {
    const cleanedCurrentUrl = window.location.href.replace(/panel=support[^&]*(&)?/, '').replace(/#$/, '')
    return `\nLocation: ${cleanedCurrentUrl}`
}

function getSessionReplayLink(): string {
    const replayUrl = posthog
        .get_session_replay_url({ withTimestamp: true, timestampLookBack: 30 })
        .replace(window.location.origin + '/replay/', 'http://go/session/')
    return `\nSession: ${replayUrl}`
}

function getErrorTrackingLink(): string {
    const filterGroup = encodeURIComponent(
        JSON.stringify({
            type: 'AND',
            values: [
                {
                    type: 'AND',
                    values: [
                        {
                            key: '$session_id',
                            value: [posthog.get_session_id()],
                            operator: 'exact',
                            type: 'event',
                        },
                    ],
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
    const link = `http://go/admin${cloudRegion}/${user.email}`
    return `\nAdmin: ${link} (organization ID ${currentOrganization?.id}: ${currentOrganization?.name}, project ID ${currentTeam?.id}: ${currentTeam?.name})`
}

function getBillingAdminLink(currentOrganization: OrganizationBasicType | null): string {
    if (!currentOrganization) {
        return ''
    }
    return `\nBilling admin: http://go/billing/${currentOrganization.id}`
}

const SUPPORT_TICKET_KIND_TO_TITLE: Record<SupportTicketKind, string> = {
    support: 'Contact support',
    feedback: 'Give feedback',
    bug: 'Report a bug',
}

export const TARGET_AREA_TO_NAME = [
    {
        title: 'General',
        options: [
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
                value: 'data_management',
                'data-attr': `support-form-target-area-data_management`,
                label: 'Data management (incl. events, actions, properties)',
            },
            {
                value: 'login',
                'data-attr': `support-form-target-area-login`,
                label: 'Authentication (incl. login, sign-up, invites)',
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
        ],
    },
    {
        title: 'Individual product',
        options: [
            {
                value: 'analytics',
                'data-attr': `support-form-target-area-analytics`,
                label: 'Product analytics (incl. insights, dashboards, annotations)',
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
                value: 'llm-observability',
                'data-attr': `support-form-target-area-llm-observability`,
                label: 'LLM observability',
            },
            {
                value: 'max-ai',
                'data-attr': `support-form-target-area-max-ai`,
                label: 'Max AI',
            },
            {
                value: 'messaging',
                'data-attr': `support-form-target-area-messaging`,
                label: 'Messaging',
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
                value: 'surveys',
                'data-attr': `support-form-target-area-surveys`,
                label: 'Surveys',
            },
            {
                value: 'toolbar',
                'data-attr': `support-form-target-area-toolbar`,
                label: 'Toolbar (incl. heatmaps)',
            },
            {
                value: 'web_analytics',
                'data-attr': `support-form-target-area-web_analytics`,
                label: 'Web analytics',
            },
        ],
    },
]

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
    | 'experiments'
    | 'apps'
    | 'login'
    | 'billing'
    | 'onboarding'
    | 'cohorts'
    | 'data_management'
    | 'notebooks'
    | 'data_warehouse'
    | 'feature_flags'
    | 'analytics'
    | 'session_replay'
    | 'toolbar'
    | 'surveys'
    | 'web_analytics'
    | 'error_tracking'
    | 'cdp_destinations'
    | 'data_ingestion'
    | 'batch_exports'
    | 'messaging'
    | 'platform_addons'
    | 'max-ai'
export type SupportTicketSeverityLevel = keyof typeof SEVERITY_LEVEL_TO_NAME
export type SupportTicketKind = keyof typeof SUPPORT_KIND_TO_SUBJECT

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
    app: 'apps',
    toolbar: 'session_replay',
    warehouse: 'data_warehouse',
    surveys: 'surveys',
    web: 'web_analytics',
    destination: 'cdp_destinations',
    destinations: 'cdp_destinations',
    transformation: 'cdp_destinations',
    transformations: 'cdp_destinations',
    source: 'data_warehouse',
    sources: 'data_warehouse',
    messaging: 'messaging',
    billing: 'billing',
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
    isEmailFormOpen?: boolean | 'true' | 'false'
}

export const supportLogic = kea<supportLogicType>([
    props({} as SupportFormLogicProps),
    path(['lib', 'components', 'support', 'supportLogic']),
    connect(() => ({
        values: [
            userLogic,
            ['user'],
            preflightLogic,
            ['preflight'],
            sidePanelStateLogic,
            ['sidePanelAvailable'],
            userLogic,
            ['hasAvailableFeature'],
            billingLogic,
            ['billing'],
            organizationLogic,
            ['isCurrentOrganizationNew'],
        ],
        actions: [sidePanelStateLogic, ['openSidePanel', 'setSidePanelOptions']],
    })),
    actions(() => ({
        closeSupportForm: true,
        openSupportForm: (values: Partial<SupportFormFields>) => values,
        submitZendeskTicket: (form: SupportFormFields) => form,
        ensureZendeskOrganization: true,
        updateUrlParams: true,
        openEmailForm: true,
        closeEmailForm: true,
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
    })),
    forms(({ actions, values }) => ({
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
                return {
                    name: !values.user ? (!name ? 'Please enter your name' : '') : '',
                    email: !values.user ? (!email ? 'Please enter your email' : '') : '',
                    message: !message ? 'Please enter a message' : '',
                    kind: !kind ? 'Please choose' : undefined,
                    severity_level: !severity_level ? 'Please choose' : undefined,
                    target_area: !target_area ? 'Please choose' : undefined,
                }
            },
            submit: async (formValues) => {
                // name must be present for zendesk to accept the ticket
                formValues.name = values.user?.first_name ?? formValues.name ?? 'name not set'
                formValues.email = values.user?.email ?? formValues.email ?? ''
                actions.submitZendeskTicket(formValues)
                // Form closing and resetting is now handled in submitZendeskTicket listener
                // based on success/failure of the submission
            },
        },
    })),
    selectors({
        title: [
            (s) => [s.sendSupportRequest ?? null],
            (sendSupportRequest) =>
                sendSupportRequest.kind
                    ? SUPPORT_TICKET_KIND_TO_TITLE[sendSupportRequest.kind]
                    : 'Leave a message with PostHog',
        ],
        targetArea: [
            (s) => [s.sendSupportRequest],
            (sendSupportRequest: SupportFormFields) => sendSupportRequest.target_area,
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
                // Explicitly exclude message, name, and email fields
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
        }: Partial<SupportFormFields>) => {
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
                message: message ?? '',
            })

            if (isEmailFormOpen === 'true' || isEmailFormOpen === true) {
                actions.openEmailForm()
            } else {
                actions.closeEmailForm()
            }

            if (values.sidePanelAvailable) {
                const panelOptions = [kind ?? '', area ?? ''].join(':')
                actions.openSidePanel(SidePanelTab.Support, panelOptions === ':' ? undefined : panelOptions)
            } else {
                openSupportModal()
            }

            actions.updateUrlParams()
        },
        submitZendeskTicket: async ({ name, email, kind, target_area, severity_level, message }: SupportFormFields) => {
            const zendesk_ticket_uuid = uuid()
            const subject =
                SUPPORT_KIND_TO_SUBJECT[kind ?? 'support'] +
                ': ' +
                (target_area
                    ? getLabelBasedOnTargetArea(target_area) ?? `${target_area} (feature preview)`
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

            const hasBoostTrial = billing?.trial?.status === 'active' && (billing.trial?.target as any) === 'boost'
            const hasScaleTrial = billing?.trial?.status === 'active' && (billing.trial?.target as any) === 'scale'
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

            const { accountOwner } = billingLogic.values

            const ownerName = accountOwner?.name?.toLowerCase().replace(/[^a-z0-9]/g, '_') || 'unassigned'
            const accountOwnerTag = `owner_${ownerName}`

            const payload = {
                request: {
                    requester: { name: name, email: email },
                    subject: subject,
                    tags: [planLevelTag, accountOwnerTag],
                    custom_fields: [
                        {
                            id: 22084126888475,
                            value: severity_level,
                        },
                        {
                            id: 22129191462555,
                            value: posthog.get_distinct_id(),
                        },
                        {
                            id: 27242745654043,
                            value: target_area ?? '',
                        },
                        {
                            id: 27031528411291,
                            value: userLogic?.values?.user?.organization?.id ?? '',
                        },
                        {
                            id: 26073267652251,
                            value: values.hasAvailableFeature(AvailableFeature.PRIORITY_SUPPORT)
                                ? 'priority_support'
                                : values.hasAvailableFeature(AvailableFeature.EMAIL_SUPPORT)
                                ? 'email_support'
                                : 'free_support',
                        },
                        {
                            id: 37742340880411,
                            value: accountOwner?.name || 'unassigned',
                        },
                    ],
                    comment: {
                        body:
                            message +
                            `\n\n-----` +
                            `\nKind: ${kind}` +
                            `\nTarget area: ${target_area}` +
                            `\nReport event: http://go/ticketByUUID/${zendesk_ticket_uuid}` +
                            getSessionReplayLink() +
                            getErrorTrackingLink() +
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

        closeSupportForm: () => {
            // Reset the form when closing so Cancel button clears the data
            actions.resetSendSupportRequest()
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

    urlToAction(({ actions, values }) => ({
        '*': (_, _search, hashParams) => {
            if (values.isSupportFormOpen) {
                return
            }

            const [panel, ...panelOptions] = (hashParams['panel'] ?? '').split(':')

            if (panel === SidePanelTab.Support) {
                const [kind, area, severity, isEmailFormOpen] = panelOptions

                actions.openSupportForm({
                    kind: Object.keys(SUPPORT_KIND_TO_SUBJECT).includes(kind) ? kind : null,
                    target_area: getLabelBasedOnTargetArea(area) ? area : null,
                    severity_level: Object.keys(SEVERITY_LEVEL_TO_NAME).includes(severity) ? severity : null,
                    isEmailFormOpen: isEmailFormOpen ?? 'false',
                })
                return
            }

            // Legacy supportModal param
            if ('supportModal' in hashParams) {
                const [kind, area, severity] = (hashParams['supportModal'] || '').split(':')

                actions.openSupportForm({
                    kind: Object.keys(SUPPORT_KIND_TO_SUBJECT).includes(kind) ? kind : null,
                    target_area: Object.keys(TARGET_AREA_TO_NAME).includes(area) ? area : null,
                    severity_level: Object.keys(SEVERITY_LEVEL_TO_NAME).includes(severity) ? severity : null,
                })
            }
        },
    })),
])
