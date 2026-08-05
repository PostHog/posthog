import { MakeLogicType, actions, connect, kea, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import type { DeepPartial, DeepPartialMap, FieldName, ValidationErrorType } from 'kea-forms'
import posthog from 'posthog-js'

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

// Distinct from a failed send: the widget is a lazily-loaded posthog-js extension, so its absence is
// usually something no retry will fix (ad blocker, content blocker, network policy). Saying "try
// again" there sends people round a loop, so name the likely cause instead. Stays open because it
// can't be recovered from by waiting. Only call this where the user is actually entitled to email
// us — free plans have no email channel, so pointing them at one promises something they don't have.
export function warnSupportWidgetUnavailable(): void {
    lemonToast.error(
        "We can't load the support chat, so your message can't be sent. That's usually an ad blocker or a network policy.",
        { button: EMAIL_SUPPORT_BUTTON, autoClose: false }
    )
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

export const SUPPORT_KIND_TO_SUBJECT = {
    bug: 'Bug Report',
    feedback: 'Feedback',
    support: 'Support Ticket',
}

export type SupportTicketKind = keyof typeof SUPPORT_KIND_TO_SUBJECT

export type SupportTicketExceptionEvent = { uuid: string; event: string; properties?: Record<string, any> }

export const SUPPORT_TICKET_TEMPLATES = {
    bug: 'Please describe the bug you saw, and how to reproduce it.\n\nIf the bug appeared on a specific insight or dashboard, please include a link to it.',
    feedback:
        "If your request is due to a problem, please describe the problem as best you can.\n\nPlease also describe the solution you'd like to see, and any alternatives you considered.\n\nYou can add images below to help illustrate your request, if needed!",
    support:
        "Please explain as fully as possible what you're aiming to do, and what you'd like help with.\n\nIf your question involves an existing insight or dashboard, please include a link to it.",
}

export type SupportFormLogicProps = {
    onClose?: () => void
}

export type SupportFormFields = {
    name: string
    email: string
    kind: SupportTicketKind
    message: string
    /**
     * Billing questions are answered on every plan, so a billing CTA earns a support exemption even
     * when the plan itself doesn't include support. This replaced an implicit `target_area === 'billing'`
     * check, which stopped being expressible once triage fields were dropped.
     */
    billing_issue?: boolean
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
    isBillingIssue: boolean
    supportResponseTime: string | null
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
        isBillingIssue: (sendSupportRequest: SupportFormFields) => boolean
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
                message: '',
                billing_issue: false,
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
        isBillingIssue: [
            (s) => [s.sendSupportRequest],
            (sendSupportRequest: SupportFormFields) => !!sendSupportRequest.billing_issue,
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
            const panelOptions = [values.sendSupportRequest.kind ?? '', values.isEmailFormOpen ?? 'false'].join(':')

            if (panelOptions !== ':') {
                actions.setSidePanelOptions(panelOptions)
            }
        },
        openSupportForm: async ({
            name,
            email,
            isEmailFormOpen,
            kind,
            message,
            exception_event,
            billing_issue,
            target,
        }: Partial<SupportFormFields> & { target?: 'modal' | 'sidePanel' }) => {
            kind = kind ?? 'support'
            actions.resetSendSupportRequest({
                name: name ?? '',
                email: email ?? '',
                kind,
                message: message ?? values.sendSupportRequest.message ?? '',
                exception_event,
                billing_issue: billing_issue ?? false,
            })

            if (isEmailFormOpen === 'true' || isEmailFormOpen === true) {
                actions.openEmailForm()
            } else {
                actions.closeEmailForm()
            }

            const useSidePanel = target ? target === 'sidePanel' : values.sidePanelAvailable
            if (useSidePanel) {
                actions.openSidePanel(SidePanelTab.Support, kind || undefined)
            } else {
                openSupportModal()
            }

            actions.updateUrlParams()
        },
        submitSupportTicket: async (formValues: SupportFormFields) => {
            const { name, email, kind, message, exception_event } = formValues
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

            // Conversations is the only channel, so every failure has to be reported rather than
            // rerouted. `reason` splits "the widget never loaded" (usually permanent for that browser)
            // from "the send failed" (usually transient), because they need different advice and the
            // volume of each tells us whether the email fallback is carrying real traffic.
            const sendFailed = (
                reason: 'widget_unavailable' | 'widget_declined' | 'send_failed',
                error?: unknown
            ): void => {
                posthog.capture('support ticket send failed', {
                    channel: 'conversations',
                    reason,
                    error: error !== undefined ? (error instanceof Error ? error.message : String(error)) : undefined,
                    kind,
                    message_length: message?.length,
                    current_url_length: window.location.href.length,
                })
                if (reason === 'widget_unavailable') {
                    warnSupportWidgetUnavailable()
                    return
                }
                lemonToast.error("Oops, the message couldn't be sent. Please try again in a moment.", {
                    button: EMAIL_SUPPORT_BUTTON,
                })
            }

            if (!(await waitForConversations())) {
                sendFailed('widget_unavailable')
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
                    sendFailed('widget_declined')
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
                sendFailed('send_failed', e)
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
