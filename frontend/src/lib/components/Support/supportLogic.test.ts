import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { initKeaTests } from '~/test/init'
import { AppContext, SidePanelTab } from '~/types'

import {
    CONVERSATIONS_MESSAGE_MAX_LENGTH,
    SUPPORT_MESSAGE_PREVIEW_MAX_LENGTH,
    SupportFormFields,
    supportLogic,
} from './supportLogic'
import * as SupportModal from './SupportModal'

// supportLogic and SupportModal import each other, so jest.mock('./SupportModal') leaves supportLogic
// bound to the real openSupportModal — spy on the live module export instead so the call is intercepted.
const openSupportModal = jest.spyOn(SupportModal, 'openSupportModal').mockImplementation(() => {})

describe('supportLogic', () => {
    const conversationsMock = (sendMessage: jest.Mock): void => {
        ;(posthog as any).conversations = { isAvailable: () => true, sendMessage }
    }

    const sendFailures = (): unknown[][] =>
        (posthog.capture as jest.Mock).mock.calls.filter(([event]) => event === 'support ticket send blocked')

    describe('openSupportForm modal vs side panel target', () => {
        let logic: ReturnType<typeof supportLogic.build>

        beforeEach(() => {
            // sidePanelStateLogic persists its selected tab and reflects open state in the URL hash;
            // initKeaTests resets neither, so clear them to keep the gating decision deterministic.
            localStorage.clear()
            window.history.replaceState(null, '', '/')
            initKeaTests()
            sidePanelStateLogic.mount()
            logic = supportLogic.build()
            logic.mount()
            openSupportModal.mockClear()
        })

        afterEach(() => {
            logic?.unmount()
        })

        it('opens the side panel when target is sidePanel', async () => {
            await expectLogic(logic, () => {
                logic.actions.openSupportForm({ kind: 'support', target: 'sidePanel' })
            }).toFinishAllListeners()

            expect(sidePanelStateLogic.values.sidePanelOpen).toBe(true)
            expect(sidePanelStateLogic.values.selectedTab).toBe(SidePanelTab.Support)
            expect(openSupportModal).not.toHaveBeenCalled()
        })

        it('opens the modal when target is modal', async () => {
            await expectLogic(logic, () => {
                logic.actions.openSupportForm({ kind: 'support', target: 'modal' })
            }).toFinishAllListeners()

            expect(sidePanelStateLogic.values.sidePanelOpen).toBe(false)
            expect(openSupportModal).toHaveBeenCalledTimes(1)
        })

        it('falls back to sidePanelAvailable when no target is given', async () => {
            sidePanelStateLogic.actions.setSidePanelAvailable(false)
            await expectLogic(logic, () => {
                logic.actions.openSupportForm({ kind: 'support' })
            }).toFinishAllListeners()

            expect(sidePanelStateLogic.values.sidePanelOpen).toBe(false)
            expect(openSupportModal).toHaveBeenCalledTimes(1)
        })
    })

    describe('support panel URL hash lifecycle', () => {
        let logic: ReturnType<typeof supportLogic.build>

        beforeEach(() => {
            localStorage.clear()
            window.history.replaceState(null, '', '/')
            initKeaTests()
            sidePanelStateLogic.mount()
            logic = supportLogic.build()
            logic.mount()
            openSupportModal.mockClear()
        })

        afterEach(() => {
            logic?.unmount()
        })

        it('does not write the panel hash when the form opens as a modal', async () => {
            router.actions.push('/login', { next: '/home' })

            await expectLogic(logic, () => {
                logic.actions.openSupportForm({ kind: 'support', target: 'modal' })
            }).toFinishAllListeners()

            expect(router.values.hashParams['panel']).toBeUndefined()
        })

        it('clears a support deep-link hash on close when no side panel owns it', async () => {
            router.actions.push('/login', { next: '/home' }, { panel: 'support:support:false' })

            await expectLogic(logic, () => {
                logic.actions.openSupportForm({ kind: 'support', target: 'modal' })
            }).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.closeSupportForm()
            }).toFinishAllListeners()

            expect(router.values.hashParams['panel']).toBeUndefined()
            expect(router.values.location.pathname).toBe('/login')
            expect(router.values.searchParams).toEqual({ next: '/home' })
        })

        it('clears the legacy supportModal hash on close when no side panel owns it', async () => {
            router.actions.push('/login', {}, { supportModal: 'support' })

            await expectLogic(logic, () => {
                logic.actions.openSupportForm({ kind: 'support', target: 'modal' })
                logic.actions.closeSupportForm()
            }).toFinishAllListeners()

            expect(router.values.hashParams['supportModal']).toBeUndefined()
            expect(router.values.hashParams['panel']).toBeUndefined()
        })

        it('leaves the panel hash alone on close when the side panel is available', async () => {
            sidePanelStateLogic.actions.setSidePanelAvailable(true)
            router.actions.push('/project/1/home', {}, { panel: 'support:support:false' })

            await expectLogic(logic, () => {
                logic.actions.openSupportForm({ kind: 'support', target: 'sidePanel' })
                logic.actions.closeSupportForm()
            }).toFinishAllListeners()

            expect(String(router.values.hashParams['panel'])).toContain('support')
        })
    })

    describe('submitSupportTicket', () => {
        const FORM_FIELDS: SupportFormFields = {
            name: 'Max',
            email: 'max@example.com',
            kind: 'bug',
            billing_issue: true,
            message: 'Help!',
        }

        let logic: ReturnType<typeof supportLogic.build>

        const aiTicketCaptures = (): unknown[][] =>
            (posthog.capture as jest.Mock).mock.calls.filter(([event]) => event === 'posthog_ai_support_ticket_created')

        beforeEach(() => {
            ;(posthog.capture as jest.Mock).mockClear()
            initKeaTests()
            logic = supportLogic.build()
            logic.mount()
        })

        afterEach(() => {
            logic?.unmount()
            delete (posthog as any).conversations
        })

        it('sends the message through the conversations widget and records the ticket id', async () => {
            const sendMessage = jest.fn().mockResolvedValue({ ticket_id: 't1' })
            conversationsMock(sendMessage)

            await logic.asyncActions.submitSupportTicket(FORM_FIELDS)

            expect(sendMessage).toHaveBeenCalledTimes(1)
            expect(sendMessage).toHaveBeenCalledWith('Help!', { name: 'Max', email: 'max@example.com' }, true)
            expect(logic.values.lastSubmittedTicketId).toBe('t1')
        })

        it('appends exception context to the message so it survives on the ticket', async () => {
            const sendMessage = jest.fn().mockResolvedValue({ ticket_id: 't1' })
            conversationsMock(sendMessage)

            await logic.asyncActions.submitSupportTicket({
                ...FORM_FIELDS,
                exception_event: { uuid: 'exc-1', event: '$exception' },
            })

            expect(sendMessage.mock.calls[0][0]).toContain('Help!')
            expect(sendMessage.mock.calls[0][0]).toContain('Exception:')
        })

        it('accepts a submission with no topic or severity, since the form no longer collects them', async () => {
            const sendMessage = jest.fn().mockResolvedValue({ ticket_id: 't1' })
            conversationsMock(sendMessage)

            await expectLogic(logic, () => {
                logic.actions.setSendSupportRequestValue('message', 'Just a message')
                logic.actions.submitSendSupportRequest()
            }).toFinishAllListeners()

            expect(sendMessage).toHaveBeenCalledTimes(1)
            expect(sendMessage.mock.calls[0][0]).toBe('Just a message')
        })

        it('blocks an over-limit message before it reaches the widget, and reports it', async () => {
            const sendMessage = jest.fn().mockResolvedValue({ ticket_id: 't1' })
            conversationsMock(sendMessage)

            await logic.asyncActions.submitSupportTicket({
                ...FORM_FIELDS,
                message: 'a'.repeat(CONVERSATIONS_MESSAGE_MAX_LENGTH + 1),
            })

            expect(sendMessage).not.toHaveBeenCalled()
            expect(logic.values.lastSubmittedTicketId).toBeNull()
            // Rejecting client-side still loses the customer's message, so it is a reportable failure
            // rather than a quiet no-op — this path used to emit nothing at all
            expect(sendFailures()).toHaveLength(1)
            expect(sendFailures()[0][1]).toMatchObject({ reason: 'message_too_long', had_draft: true })
        })

        // The whole point of these events is that a responder can act on one from an alert without the
        // ticket that never got created. That needs the draft and a way back into the session.
        it('carries the draft and session context on a lost submit, so an alert is actionable', async () => {
            ;(posthog.get_session_id as jest.Mock).mockReturnValue('sess-1')
            // Resolved against ui_host, the shape posthog-js actually returns
            ;(posthog.get_session_replay_url as jest.Mock).mockReturnValue(
                'https://us.posthog.com/project/sTMFPsFhdP1Ssg/replay/sess-1?t=30'
            )
            conversationsMock(jest.fn().mockRejectedValue(new Error('network down')))

            await logic.asyncActions.submitSupportTicket({ ...FORM_FIELDS, message: 'Billing is broken' })

            expect(sendFailures()[0][1]).toMatchObject({
                surface: 'support_form',
                reason: 'send_failed',
                error: 'network down',
                had_draft: true,
                message_preview: 'Billing is broken',
                message_truncated: false,
                session_id: 'sess-1',
                session_replay_url: 'https://us.posthog.com/project/sTMFPsFhdP1Ssg/replay/sess-1?t=30',
            })
        })

        it('truncates a long draft rather than putting a whole document in an event property', async () => {
            conversationsMock(jest.fn().mockResolvedValue(null))

            await logic.asyncActions.submitSupportTicket({
                ...FORM_FIELDS,
                message: 'b'.repeat(SUPPORT_MESSAGE_PREVIEW_MAX_LENGTH + 500),
            })

            const properties = sendFailures()[0][1] as Record<string, any>
            expect(properties.message_preview).toHaveLength(SUPPORT_MESSAGE_PREVIEW_MAX_LENGTH)
            expect(properties.message_truncated).toBe(true)
            // The real length still travels, so the preview being capped doesn't hide how much was lost
            expect(properties.message_length).toBe(SUPPORT_MESSAGE_PREVIEW_MAX_LENGTH + 500)
        })

        // lastSubmittedTicketId staying null is how every caller detects failure, and there is no
        // second channel to retry on, so each of these must report rather than silently drop. The
        // reason has to survive too: it drives which advice the user gets.
        it.each([
            ['the widget declines to send', jest.fn().mockResolvedValue(null), 'widget_declined'],
            ['the send throws', jest.fn().mockRejectedValue(new Error('network down')), 'send_failed'],
        ])('reports a failure and files no ticket when %s', async (_case, sendMessage, expectedReason) => {
            conversationsMock(sendMessage)

            await logic.asyncActions.submitSupportTicket(FORM_FIELDS)

            expect(logic.values.lastSubmittedTicketId).toBeNull()
            expect(sendFailures()).toHaveLength(1)
            expect(sendFailures()[0][1]).toMatchObject({ reason: expectedReason })
        })

        it('waits for the lazily-loaded extension, then reports a failure if it never arrives', async () => {
            ;(posthog as any).conversations = undefined

            jest.useFakeTimers()
            try {
                const promise = logic.asyncActions.submitSupportTicket(FORM_FIELDS)
                // Still waiting on the extension, so nothing is reported yet
                expect(sendFailures()).toHaveLength(0)
                await jest.runAllTimersAsync()
                await promise
            } finally {
                jest.useRealTimers()
            }

            // Reported as unavailable, not as a failed send: a blocked script won't come back, so the
            // user gets the email address instead of being told to retry
            expect(sendFailures()).toHaveLength(1)
            expect(sendFailures()[0][1]).toMatchObject({ reason: 'widget_unavailable' })
            expect(logic.values.lastSubmittedTicketId).toBeNull()
        })

        // Regression guard: this event used to live in a component effect that raced the async
        // conversations round-trip and silently dropped it. It belongs here, where the ticket id lands.
        it('captures the AI ticket event once when the submission carries AI context', async () => {
            conversationsMock(jest.fn().mockResolvedValue({ ticket_id: 't1' }))

            await logic.asyncActions.submitSupportTicket({
                ...FORM_FIELDS,
                ai_conversation_id: 'conv-1',
                ai_trace_id: 'trace-1',
                ai_feedback_rating: 'bad',
            })

            expect(aiTicketCaptures()).toEqual([
                [
                    'posthog_ai_support_ticket_created',
                    {
                        $ai_conversation_id: 'conv-1',
                        $ai_session_id: 'conv-1',
                        $ai_trace_id: 'trace-1',
                        $ai_support_ticket_id: 't1',
                        $ai_feedback_rating: 'bad',
                    },
                ],
            ])
        })

        it('does not capture the AI ticket event for a regular submission', async () => {
            conversationsMock(jest.fn().mockResolvedValue({ ticket_id: 't1' }))

            await logic.asyncActions.submitSupportTicket(FORM_FIELDS)

            expect(aiTicketCaptures()).toHaveLength(0)
        })
    })

    // Nobody is signed in on /login or /reset, so the form asks for an address, and it is the only
    // route back to whoever filed the ticket. An unusable one still files it but orphans it: replies
    // to a widget ticket are in-app only, and restore-by-email matches anonymous_traits.email, so a
    // first name in that field leaves the person no way back once the browser session is gone.
    describe('email validation when logged out', () => {
        let logic: ReturnType<typeof supportLogic.build>

        const LOGGED_OUT_FIELDS: SupportFormFields = {
            name: 'Jane',
            email: 'jane@example.com',
            kind: 'support',
            billing_issue: false,
            message: 'Help!',
        }

        beforeEach(() => {
            ;(posthog.capture as jest.Mock).mockClear()
            // initKeaTests bootstraps a user, which would leave the guard unreachable
            window.POSTHOG_APP_CONTEXT = { current_user: null } as unknown as AppContext
            initKeaTests()
            logic = supportLogic.build()
            logic.mount()
        })

        afterEach(() => {
            logic?.unmount()
            delete (posthog as any).conversations
            // Clear so the next test gets initKeaTests' usual bootstrapped user
            delete window.POSTHOG_APP_CONTEXT
        })

        it.each([
            ['a first name', 'Jane'],
            ['an address with no TLD to deliver to', 'jane@localhost'],
        ])('blocks the form submit and says why for %s', async (_case, email) => {
            const sendMessage = jest.fn().mockResolvedValue({ ticket_id: 't1' })
            conversationsMock(sendMessage)
            logic.actions.setSendSupportRequestValues({ ...LOGGED_OUT_FIELDS, email })

            await expectLogic(logic, () => {
                logic.actions.submitSendSupportRequest()
            }).toFinishAllListeners()

            expect(logic.values.sendSupportRequestErrors.email).toBe('Please enter a valid email address')
            expect(sendMessage).not.toHaveBeenCalled()
        })

        // Over-blocking would be the worse regression: it would take away the only support channel
        // someone locked out of their account has. Pasted addresses often carry stray whitespace,
        // so those must pass too — trimmed, since restore-by-email matches the stored value exactly.
        it.each([
            ['a real address', 'jane@example.com'],
            ['a real address pasted with whitespace', ' jane@example.com '],
        ])('still files the ticket for %s, sending it trimmed', async (_case, email) => {
            const sendMessage = jest.fn().mockResolvedValue({ ticket_id: 't1' })
            conversationsMock(sendMessage)
            logic.actions.setSendSupportRequestValues({ ...LOGGED_OUT_FIELDS, email })

            await expectLogic(logic, () => {
                logic.actions.submitSendSupportRequest()
            }).toFinishAllListeners()

            expect(logic.values.sendSupportRequestErrors.email).toBeUndefined()
            expect(sendMessage).toHaveBeenCalledWith('Help!', { name: 'Jane', email: 'jane@example.com' }, true)
        })

        // The PostHog AI handovers submit through a plain onClick rather than a form submit, so they
        // never run the validator above — the address has to be checked on the path every caller shares
        it.each([
            ['a malformed address', 'Jane'],
            ['no address at all', ''],
        ])('files no ticket when a caller bypasses the form with %s', async (_case, email) => {
            const sendMessage = jest.fn().mockResolvedValue({ ticket_id: 't1' })
            conversationsMock(sendMessage)

            await logic.asyncActions.submitSupportTicket({ ...LOGGED_OUT_FIELDS, email })

            expect(sendMessage).not.toHaveBeenCalled()
            expect(logic.values.lastSubmittedTicketId).toBeNull()
            expect(sendFailures()).toHaveLength(1)
            expect(sendFailures()[0][1]).toMatchObject({ reason: 'invalid_email' })
        })
    })
})
