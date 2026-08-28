import { MakeLogicType, actions, connect, kea, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import type { DeepPartial, DeepPartialMap, FieldName, ValidationErrorType } from 'kea-forms'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import { EMAIL_SUPPORT_BUTTON, lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { isEmail } from 'lib/utils/url'
import { billingLogic } from 'scenes/billing/billingLogic'
import { userLogic } from 'scenes/userLogic'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { BillingPlan, BillingPlanType, SidePanelTab, UserType } from '~/types'

import type { BillingType } from '../../../types'
import { parseExceptionEvent } from './exceptionUtils'
import { openSupportModal } from './SupportModal'
import { getSupportResponseTime } from './supportResponseTime'

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

// One email rule shared by the form validator and the submit guard, so the two can't drift.
// Trimmed because pasted addresses often carry stray whitespace; requireTLD because an address
// without one can't be delivered to, making it no better than a blank field for replying.
const isDeliverableEmail = (email: string): boolean => isEmail(email.trim(), { requireTLD: true })

/** Where the customer was when support broke for them. */
export type SupportFailureSurface =
    | 'support_form' // the modal / side-panel support form (every "contact support" CTA)
    | 'side_panel_composer' // the conversations composer in the support panel
    | 'side_panel_tickets' // the panel's ticket list and message threads
    | 'restore_form' // "email me a link to my tickets"

/** Why a submitted message never became a ticket. Every one of these loses customer intent. */
export type SupportSendFailureReason =
    | 'widget_unavailable' // extension never loaded (ad blocker, network policy) — no retry will fix it
    | 'widget_declined' // extension returned no response; nothing left the browser
    | 'send_failed' // the request threw
    | 'message_too_long' // rejected by the client-side cap before we tried
    | 'not_entitled' // plan has no ticket channel, so the draft was dropped on the floor
    | 'invalid_email' // logged-out submit with no usable reply address, so the ticket would be orphaned

/** Why a support surface couldn't function. Nothing was submitted, so no message is at risk. */
export type SupportLoadFailureReason =
    | 'extension_missing' // posthog.conversations never showed up
    | 'tickets_load_failed' // listing existing tickets threw
    | 'thread_load_failed' // opening a ticket's messages threw
    | 'restore_link_failed' // a request rather than a load, but the same "surface can't do its job"

// Event properties are no place to store a document, so the draft an alert carries is capped.
export const SUPPORT_MESSAGE_PREVIEW_MAX_LENGTH = 1000

export const SUPPORT_WIDGET_UNAVAILABLE_MESSAGE =
    "We can't load the support chat, which is usually an ad blocker or a network policy."

// `current_url` is explicit rather than autocapture's `$current_url`, so an alert template reading
// these properties doesn't depend on autocapture staying enabled. The recording lives in PostHog's
// own telemetry project, so the replay link is for staff triaging the alert, never the reporter.
function supportFailureContext(): Record<string, any> {
    return {
        session_id: posthog.get_session_id?.() ?? null,
        session_replay_url: posthog.get_session_replay_url?.({ withTimestamp: true, timestampLookBack: 30 }) ?? null,
        current_url: window.location.href,
    }
}

function errorMessage(error: unknown): string | undefined {
    if (error === undefined) {
        return undefined
    }
    return error instanceof Error ? error.message : String(error)
}

// Always the same keys, so the event stays queryable whether or not anything had been typed
function messagePreviewProperties(message?: string): Record<string, any> {
    const draft = message?.trim() ?? ''
    return {
        had_draft: !!draft,
        message_length: draft.length,
        message_truncated: draft.length > SUPPORT_MESSAGE_PREVIEW_MAX_LENGTH,
        message_preview: draft.slice(0, SUPPORT_MESSAGE_PREVIEW_MAX_LENGTH),
    }
}

// Deliberately a different event from the widget endpoint's own `support ticket send failed`, which
// reports requests the server rejected. That one names the offending field but has no session and no
// draft, so only an engineer can act on it. This one means the message never left the browser, so it
// carries what the customer wrote and someone can follow up. Two audiences, so keep them apart.
export function captureSupportTicketBlocked({
    surface,
    reason,
    message,
    error,
    ...rest
}: {
    surface: SupportFailureSurface
    reason: SupportSendFailureReason
    message?: string
    error?: unknown
    kind?: SupportTicketKind | null
    is_new_ticket?: boolean
    can_create_ticket?: boolean
}): void {
    posthog.capture('support ticket send blocked', {
        channel: 'conversations',
        surface,
        reason,
        error: errorMessage(error),
        ...messagePreviewProperties(message),
        ...supportFailureContext(),
        ...rest,
    })
}

// The rate signal for "support is broken for people", as opposed to the per-message loss above.
export function captureSupportWidgetLoadFailed({
    surface,
    reason,
    error,
    ...rest
}: {
    surface: SupportFailureSurface
    reason: SupportLoadFailureReason
    error?: unknown
    can_create_ticket?: boolean
}): void {
    posthog.capture('support widget load failed', {
        surface,
        reason,
        error: errorMessage(error),
        ...supportFailureContext(),
        ...rest,
    })
}

// Returns true when the message exceeds the cap the widget endpoint enforces, so callers can bail
// before the network. Callers report it: the customer pressed send and has no ticket.
export function warnIfMessageTooLong(message: string): boolean {
    if (message.length > CONVERSATIONS_MESSAGE_MAX_LENGTH) {
        lemonToast.error(
            `Your message is too long (max ${CONVERSATIONS_MESSAGE_MAX_LENGTH.toLocaleString()} characters). Please shorten it or send it in multiple messages.`
        )
        return true
    }
    return false
}

// The widget is a lazily-loaded posthog-js extension, so its absence is rarely something a retry
// fixes — name the likely cause instead of saying "try again", and stay open because waiting won't
// help. Only for users entitled to email us: a free plan has no email channel to point at.
export function warnSupportWidgetUnavailable(): void {
    lemonToast.error(SUPPORT_WIDGET_UNAVAILABLE_MESSAGE, { button: EMAIL_SUPPORT_BUTTON, autoClose: false })
}

// Conversations tickets carry just the user's message (like the side panel composer), but for bug
// reports we still fold the exception in so it survives on email-channel tickets and when the
// agent's session-scoped exceptions panel can't resolve it. Mirrors how feature-preview feedback
// names its feature in the message body.
export function appendExceptionToMessage(message: string, exception_event?: SupportTicketExceptionEvent): string {
    if (!exception_event) {
        return message
    }
    const exception = `Exception: ${parseExceptionEvent(exception_event)}`
    // The separator divides the user's own words from the machine context, so it only earns its place
    // when there are words above it — an error boundary CTA carries an exception and nothing else.
    return message ? `${message}\n\n-----\n${exception}` : exception
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
    isBillingIssue: boolean
    isEmailFormOpen: boolean
    isErrorReport: boolean
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
        isErrorReport: (sendSupportRequest: SupportFormFields) => boolean
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
                    email: !values.user
                        ? !email.trim()
                            ? 'Please enter your email'
                            : !isDeliverableEmail(email)
                              ? 'Please enter a valid email address'
                              : undefined
                        : undefined,
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
        // A crash we surfaced ourselves. The error boundary offers to email an engineer, so this
        // earns a support exemption the same way a billing question does — see canCreateTicket.
        isErrorReport: [
            (s) => [s.sendSupportRequest],
            (sendSupportRequest: SupportFormFields) => !!sendSupportRequest.exception_event,
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
            if (!values.sidePanelAvailable) {
                return
            }

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
            const { name, kind, message, exception_event } = formValues
            // Trimmed before validating and sending: restore-by-email matches the stored trait
            // exactly, so stray whitespace would make the ticket unrecoverable
            const email = formValues.email.trim()
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
            const sendFailed = (reason: SupportSendFailureReason, error?: unknown): void => {
                captureSupportTicketBlocked({ surface: 'support_form', reason, message, error, kind })
                if (reason === 'widget_unavailable') {
                    warnSupportWidgetUnavailable()
                    return
                }
                lemonToast.error("Oops, the message couldn't be sent. Please try again in a moment.", {
                    button: EMAIL_SUPPORT_BUTTON,
                })
            }

            // The form's own validator only runs on a form submit, and the PostHog AI handovers submit
            // straight from a button — so the reply address is checked here, on the path every caller
            // shares. Without one a logged-out ticket is unreachable: widget replies are in-app only,
            // and restoring by email is the sole way back if that browser session is gone.
            if (!values.user && !isDeliverableEmail(email)) {
                captureSupportTicketBlocked({ surface: 'support_form', reason: 'invalid_email', message, kind })
                lemonToast.error('Please enter a valid email address so our support engineers can reply.')
                return
            }

            if (!(await waitForConversations())) {
                sendFailed('widget_unavailable')
                return
            }

            // Measure the full outgoing payload (message plus any appended exception) so the guard
            // matches what the widget endpoint actually receives and rejects
            const outgoingMessage = appendExceptionToMessage(message, exception_event)
            if (warnIfMessageTooLong(outgoingMessage)) {
                captureSupportTicketBlocked({
                    surface: 'support_form',
                    reason: 'message_too_long',
                    message: outgoingMessage,
                    kind,
                })
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
            if (!values.sidePanelAvailable) {
                const hashParams = { ...router.values.hashParams }
                let changed = false
                if (String(hashParams['panel'] ?? '').split(':')[0] === SidePanelTab.Support) {
                    delete hashParams['panel']
                    changed = true
                }
                if ('supportModal' in hashParams) {
                    delete hashParams['supportModal']
                    changed = true
                }
                if (changed) {
                    router.actions.replace(router.values.location.pathname, router.values.searchParams, hashParams)
                }
            }

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
