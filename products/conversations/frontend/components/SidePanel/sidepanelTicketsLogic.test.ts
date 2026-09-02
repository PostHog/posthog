import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { CONVERSATIONS_MESSAGE_MAX_LENGTH, supportLogic } from 'lib/components/Support/supportLogic'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { billingLogic } from 'scenes/billing/billingLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { urls } from 'scenes/urls'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { initKeaTests } from '~/test/init'
import { BillingType, SidePanelTab } from '~/types'

import type { ConversationTicket } from '../../types'
import { sidepanelTicketsLogic } from './sidepanelTicketsLogic'

describe('sidepanelTicketsLogic', () => {
    let logic: ReturnType<typeof sidepanelTicketsLogic.build>

    const setSubscriptionLevel = (subscriptionLevel: BillingType['subscription_level']): void => {
        billingLogic.actions.loadBillingSuccess({ subscription_level: subscriptionLevel } as BillingType)
    }

    beforeEach(() => {
        initKeaTests()
        ;(posthog as any).conversations = {
            isAvailable: () => true,
            getTickets: jest.fn().mockResolvedValue({ results: [] }),
            getMessages: jest.fn().mockResolvedValue({ messages: [], has_more: false }),
            markAsRead: jest.fn().mockResolvedValue({}),
            sendMessage: jest
                .fn()
                .mockResolvedValue({ ticket_id: 't1', ticket_status: 'open', created_at: '2026-07-21T00:00:00Z' }),
        }
        supportLogic.mount()
        billingLogic.mount()
        // Tickets can be created unless a test drops the plan; set it up front, since the async
        // fixture load lands too late for the intent a test may already have queued
        setSubscriptionLevel('paid')
    })

    afterEach(() => {
        logic?.unmount()
        delete (posthog as any).conversations
    })

    // We don't support self-hosted, and the conversations extension is cloud-only — but this logic
    // mounts there anyway, because the tickets scene declares it in its SceneExport. Left ungated it
    // retries a widget that never arrives and then tells a self-hosted user to email us, contradicting
    // the community-forum message the scene itself renders.
    it('does not touch the conversations widget on self-hosted', async () => {
        preflightLogic.mount()
        preflightLogic.actions.loadPreflightSuccess({ cloud: false, is_debug: false } as any)
        ;(posthog.capture as jest.Mock).mockClear()

        logic = sidepanelTicketsLogic.build()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect((posthog as any).conversations.getTickets).not.toHaveBeenCalled()
        expect(
            (posthog.capture as jest.Mock).mock.calls.filter(([event]) => event === 'support widget load failed')
        ).toHaveLength(0)
    })

    it('opens the composer with the prefilled message when the support form intent exists at mount', async () => {
        supportLogic.actions.openSupportForm({
            kind: 'bug',
            isEmailFormOpen: true,
            message: 'It broke',
            target: 'sidePanel',
        })

        logic = sidepanelTicketsLogic.build()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.view).toBe('new')
        expect(JSON.stringify(logic.values.newTicketDraft)).toContain('It broke')
        expect(supportLogic.values.isEmailFormOpen).toBe(false)

        // Leaving the composer clears the prefill so a later blank "New ticket" starts empty
        logic.actions.setView('list')
        expect(logic.values.newTicketDraft).toBeNull()
    })

    it('switches to the composer when the support form opens while already mounted', async () => {
        logic = sidepanelTicketsLogic.build()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.view).toBe('list')

        await expectLogic(logic, () => {
            supportLogic.actions.openSupportForm({
                kind: 'support',
                isEmailFormOpen: true,
                target: 'sidePanel',
            })
        }).toFinishAllListeners()

        expect(logic.values.view).toBe('new')
        expect(supportLogic.values.isEmailFormOpen).toBe(false)
    })

    it.each([
        ['a general CTA lands on the list view', false, 'list'],
        // Billing problems are answered on every plan
        ['a billing CTA lands on the composer', true, 'new'],
    ])('on a free plan, %s', async (_name, billingIssue, expectedView) => {
        logic = sidepanelTicketsLogic.build()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        // After the mount, so the fixture load doesn't put the paid plan back
        setSubscriptionLevel('free')

        await expectLogic(logic, () => {
            supportLogic.actions.openSupportForm({
                kind: 'bug',
                billing_issue: billingIssue as boolean,
                isEmailFormOpen: true,
                message: 'It broke',
                target: 'sidePanel',
            })
        }).toFinishAllListeners()

        expect(logic.values.view).toBe(expectedView)
        // Either way the intent is consumed, so supportRouterLogic doesn't keep replaying it
        expect(supportLogic.values.isEmailFormOpen).toBe(false)
    })

    // An ineligible plan is turned away before a composer ever opens, so what's lost is the intent to
    // reach us rather than anything typed. Modelled on a real CTA (FeedbackNotice, the session
    // attribution explorer): they pass no message, so `had_draft` must not claim otherwise.
    it('reports the turned-away intent when an ineligible plan hits a support CTA', async () => {
        logic = sidepanelTicketsLogic.build()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        setSubscriptionLevel('free')
        ;(posthog.capture as jest.Mock).mockClear()

        await expectLogic(logic, () => {
            supportLogic.actions.openSupportForm({ kind: 'bug', isEmailFormOpen: true, target: 'sidePanel' })
        }).toFinishAllListeners()

        const failures = (posthog.capture as jest.Mock).mock.calls.filter(
            ([event]) => event === 'support ticket send blocked'
        )
        expect(failures).toHaveLength(1)
        expect(failures[0][1]).toMatchObject({
            reason: 'not_entitled',
            can_create_ticket: false,
            had_draft: false,
        })
        // The composer never opened, so there is no draft to report — asserting this stops the field
        // from quietly starting to carry a stale leftover from an earlier form interaction
        expect(failures[0][1]).toMatchObject({ message_preview: '', message_length: 0 })
    })

    // Half the billing CTAs (Billing.tsx, ConfirmDowngradeModal, PurchaseCreditsModal) open the panel
    // without setting isEmailFormOpen, so they never reach `startTicketFromSupportForm`. The exemption
    // has to hold for them too, or a free plan lands on a panel with no composer and no explanation.
    it('grants the billing exemption to a CTA that never opens the composer', async () => {
        logic = sidepanelTicketsLogic.build()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        setSubscriptionLevel('free')
        expect(logic.values.canCreateTicket).toBe(false)

        await expectLogic(logic, () => {
            supportLogic.actions.openSupportForm({ kind: 'bug', billing_issue: true, target: 'sidePanel' })
        }).toFinishAllListeners()

        expect(logic.values.canCreateTicket).toBe(true)
    })

    // The error boundary offers to "email an engineer" on a crash. Blocking that on plan would break a
    // promise we just made on screen, and a crash we surfaced ourselves is always worth hearing about.
    it('lets an ineligible plan report a crash from the error boundary', async () => {
        logic = sidepanelTicketsLogic.build()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        setSubscriptionLevel('free')
        expect(logic.values.canCreateTicket).toBe(false)
        ;(posthog.capture as jest.Mock).mockClear()

        await expectLogic(logic, () => {
            supportLogic.actions.openSupportForm({
                kind: 'bug',
                isEmailFormOpen: true,
                exception_event: { uuid: 'exc-1', event: '$exception' },
                target: 'sidePanel',
            })
        }).toFinishAllListeners()

        expect(logic.values.canCreateTicket).toBe(true)
        expect(logic.values.view).toBe('new')
        // Nothing was turned away, so there is no lost-submit to report
        expect(
            (posthog.capture as jest.Mock).mock.calls.filter(([event]) => event === 'support ticket send blocked')
        ).toHaveLength(0)
    })

    // Covers the live `isErrorReport` arm rather than the sticky reducer: a CTA that carries an
    // exception without opening the composer never reaches `startTicketFromSupportForm`, which is
    // exactly how three billing CTAs silently lost their exemption.
    it('grants the exemption to a crash report that never opens the composer', async () => {
        logic = sidepanelTicketsLogic.build()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        setSubscriptionLevel('free')
        expect(logic.values.canCreateTicket).toBe(false)

        await expectLogic(logic, () => {
            supportLogic.actions.openSupportForm({
                kind: 'bug',
                exception_event: { uuid: 'exc-1', event: '$exception' },
                target: 'sidePanel',
            })
        }).toFinishAllListeners()

        expect(logic.values.hasSupportExemption).toBe(false)
        expect(logic.values.canCreateTicket).toBe(true)
    })

    // The crash card promises "we'll attach the exception ID, stack trace and session replay". It sends
    // an exception and no message, so a prefill guarded on the message alone dropped it silently.
    it('carries the exception into the composer even when the CTA sends no message', async () => {
        logic = sidepanelTicketsLogic.build()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        await expectLogic(logic, () => {
            supportLogic.actions.openSupportForm({
                kind: 'bug',
                isEmailFormOpen: true,
                exception_event: { uuid: 'exc-1', event: '$exception' },
                target: 'sidePanel',
            })
        }).toFinishAllListeners()

        expect(JSON.stringify(logic.values.newTicketDraft)).toContain('Exception')
    })

    it('keeps the billing exemption after the support form resets, so backing out of the composer is not a dead end', async () => {
        logic = sidepanelTicketsLogic.build()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        setSubscriptionLevel('free')
        expect(logic.values.canCreateTicket).toBe(false)

        await expectLogic(logic, () => {
            supportLogic.actions.openSupportForm({
                kind: 'support',
                billing_issue: true,
                isEmailFormOpen: true,
                target: 'sidePanel',
            })
        }).toFinishAllListeners()

        // supportLogic has already cleared billing_issue by now, so an exemption read off it would be gone
        expect(supportLogic.values.isBillingIssue).toBe(false)
        expect(logic.values.canCreateTicket).toBe(true)

        logic.actions.setView('list')
        expect(logic.values.canCreateTicket).toBe(true)
    })

    it('opens the composer while entitlement is still unknown rather than discarding the request', async () => {
        logic = sidepanelTicketsLogic.build()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        // billing is lazily loaded, so a CTA can fire before it resolves — for a paid customer,
        // consuming the intent here would silently drop their message
        billingLogic.actions.loadBilling()
        expect(logic.values.isBillingResolved).toBe(false)

        supportLogic.actions.openSupportForm({
            kind: 'bug',
            isEmailFormOpen: true,
            message: 'It broke',
            target: 'sidePanel',
        })

        expect(logic.values.view).toBe('new')
        expect(JSON.stringify(logic.values.newTicketDraft)).toContain('It broke')
    })

    it('opens the specific ticket thread when a submission toast "View" is clicked', async () => {
        logic = sidepanelTicketsLogic.build()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        await expectLogic(logic, () => {
            supportLogic.actions.viewConversationsTicket({
                id: 'ticket-1',
                status: 'open',
                created_at: '2026-07-13T00:00:00Z',
            })
        }).toFinishAllListeners()

        expect(logic.values.view).toBe('ticket')
        expect(logic.values.currentTicket?.id).toBe('ticket-1')
        expect(supportLogic.values.pendingViewTicket).toBeNull()
    })

    // A ?ticket= deep link lands before the ticket list loads, so the id has to wait for it
    it.each([
        ['opens the linked ticket once tickets load', 't2', 'ticket', 't2'],
        ['falls back to the list when the linked ticket does not exist', 'gone', 'list', undefined],
    ])('%s', async (_case, linkedId, expectedView, expectedTicketId) => {
        ;(posthog as any).conversations.getTickets = jest.fn().mockResolvedValue({
            results: [
                { id: 't1', status: 'open', message_count: 1, created_at: '2026-07-13T00:00:00Z' },
                { id: 't2', status: 'open', message_count: 1, created_at: '2026-07-14T00:00:00Z' },
            ],
        })
        router.actions.push(urls.myTickets(linkedId))

        logic = sidepanelTicketsLogic.build()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.view).toBe(expectedView)
        expect(logic.values.currentTicket?.id).toBe(expectedTicketId)
        // Consumed either way, so a later poll can't yank the view
        expect(logic.values.pendingTicketId).toBeNull()
    })

    it('opens the ticket a `#panel=support:ticket:` deep link points at', async () => {
        ;(posthog as any).conversations.getTickets = jest.fn().mockResolvedValue({
            results: [
                { id: 't1', status: 'open', message_count: 1, created_at: '2026-07-13T00:00:00Z' },
                { id: 't2', status: 'open', message_count: 1, created_at: '2026-07-14T00:00:00Z' },
            ],
        })
        sidePanelStateLogic.mount()
        sidePanelStateLogic.actions.openSidePanel(SidePanelTab.Support, 'ticket:t2')

        logic = sidepanelTicketsLogic.build()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.view).toBe('ticket')
        expect(logic.values.currentTicket?.id).toBe('t2')
    })

    it('mirrors the open ticket into the panel options and clears them on leaving the thread', async () => {
        sidePanelStateLogic.mount()
        sidePanelStateLogic.actions.openSidePanel(SidePanelTab.Support)

        logic = sidepanelTicketsLogic.build()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        await expectLogic(logic, () => {
            logic.actions.setCurrentTicket({
                id: 't1',
                status: 'open',
                message_count: 1,
                created_at: '2026-07-13T00:00:00Z',
            } as ConversationTicket)
        }).toFinishAllListeners()
        expect(sidePanelStateLogic.values.selectedTabOptions).toBe('ticket:t1')

        logic.actions.setView('list')
        // The hash round-trip re-parses cleared options as '' rather than null; both mean none
        expect(sidePanelStateLogic.values.selectedTabOptions ?? '').toBe('')
    })

    it('keeps the URL in sync with the selected ticket on the full-screen scene', async () => {
        router.actions.push(urls.myTickets())
        logic = sidepanelTicketsLogic.build()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        await expectLogic(logic, () => {
            logic.actions.setCurrentTicket({
                id: 't1',
                status: 'open',
                message_count: 1,
                created_at: '2026-07-13T00:00:00Z',
            } as ConversationTicket)
        }).toFinishAllListeners()
        expect(router.values.searchParams['ticket']).toBe('t1')

        router.actions.push(urls.myTickets())
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.view).toBe('list')
    })

    // The panel already shows free plans the community and upgrade options, and they have no email
    // channel, so warning them the chat failed would offer support they don't actually get. The
    // unread badge also mounts this logic on every page, so outside a support surface the toast
    // would interrupt unrelated work (and block clicks under the toast container) for anyone whose
    // ad blocker keeps the widget from loading.
    it.each([
        ['warns an entitled plan on the support panel', 'paid', true, true],
        ['stays quiet on a free plan', 'free', true, false],
        ['stays quiet outside support surfaces', 'paid', false, false],
    ])('when the widget never loads, %s', async (_case, subscriptionLevel, onSupportPanel, expectWarning) => {
        const errorToast = jest.spyOn(lemonToast, 'error').mockReturnValue('' as never)
        if (onSupportPanel) {
            sidePanelStateLogic.mount()
            sidePanelStateLogic.actions.openSidePanel(SidePanelTab.Support)
        }
        logic = sidepanelTicketsLogic.build()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        // After the mount, so the fixture loads don't put the paid plan back. canCreateTicket also
        // passes for orgs under three months old, so age the org out to make "free" really unentitled.
        setSubscriptionLevel(subscriptionLevel as 'paid' | 'free')
        organizationLogic.actions.loadCurrentOrganizationSuccess({
            ...organizationLogic.values.currentOrganization,
            created_at: '2020-01-01T00:00:00Z',
        } as never)

        // Spending the retry budget is the only way into this branch, and burning it through 20 real
        // timer cycles races the fixture loads
        delete (posthog as any).conversations
        logic.cache.conversationsRetries = 20
        ;(posthog.capture as jest.Mock).mockClear()

        await expectLogic(logic, () => {
            logic.actions.loadTickets()
        }).toFinishAllListeners()

        // Recorded either way, so the failure rate stays visible even where we don't interrupt
        const loadFailures = (posthog.capture as jest.Mock).mock.calls.filter(
            ([event]) => event === 'support widget load failed'
        )
        expect(loadFailures).toHaveLength(1)
        expect(loadFailures[0][1]).toMatchObject({ can_create_ticket: subscriptionLevel === 'paid' })
        expect(errorToast).toHaveBeenCalledTimes(expectWarning ? 1 : 0)
        errorToast.mockRestore()
    })

    it('reports a missing widget instead of silently dropping the composed message', async () => {
        logic = sidepanelTicketsLogic.build()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        ;(posthog.capture as jest.Mock).mockClear()

        // The extension can go missing after mount (blocked script, teardown). Sending used to return
        // early with no toast and no loading state, leaving the typed message stranded.
        delete (posthog as any).conversations
        const onSuccess = jest.fn()

        await expectLogic(logic, () => {
            logic.actions.sendMessage('please help', onSuccess)
        }).toFinishAllListeners()

        expect(onSuccess).not.toHaveBeenCalled()
        expect(logic.values.messageSending).toBe(false)
        const failures = (posthog.capture as jest.Mock).mock.calls.filter(
            ([event]) => event === 'support ticket send blocked'
        )
        expect(failures).toHaveLength(1)
        expect(failures[0][1]).toMatchObject({ reason: 'widget_unavailable' })
    })

    it('blocks an over-limit message client-side but sends a normal one', async () => {
        logic = sidepanelTicketsLogic.build()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        const send = (posthog as any).conversations.sendMessage

        await expectLogic(logic, () => {
            logic.actions.sendMessage('a short reply', jest.fn())
        }).toFinishAllListeners()
        expect(send).toHaveBeenCalledTimes(1)

        await expectLogic(logic, () => {
            logic.actions.sendMessage('a'.repeat(CONVERSATIONS_MESSAGE_MAX_LENGTH + 1), jest.fn())
        }).toFinishAllListeners()
        // still 1: the over-limit message is rejected before reaching the widget endpoint
        expect(send).toHaveBeenCalledTimes(1)
        expect(logic.values.messageSending).toBe(false)
    })

    // A declined send is the case the widget endpoint can't report for us — nothing reached it — and
    // the reply the customer typed only exists in this composer, so the event has to carry it.
    it('reports a declined send from the composer with the reply that was lost', async () => {
        logic = sidepanelTicketsLogic.build()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        ;(posthog as any).conversations.sendMessage = jest.fn().mockResolvedValue(null)
        ;(posthog.capture as jest.Mock).mockClear()
        const onSuccess = jest.fn()

        await expectLogic(logic, () => {
            logic.actions.sendMessage('here is the error I get', onSuccess)
        }).toFinishAllListeners()

        expect(onSuccess).not.toHaveBeenCalled()
        const failures = (posthog.capture as jest.Mock).mock.calls.filter(
            ([event]) => event === 'support ticket send blocked'
        )
        expect(failures).toHaveLength(1)
        expect(failures[0][1]).toMatchObject({
            surface: 'side_panel_composer',
            reason: 'widget_declined',
            message_preview: 'here is the error I get',
        })
    })
})
