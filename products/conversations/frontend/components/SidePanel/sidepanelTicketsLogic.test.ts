import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { CONVERSATIONS_MESSAGE_MAX_LENGTH, supportLogic } from 'lib/components/Support/supportLogic'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { billingLogic } from 'scenes/billing/billingLogic'
import { organizationLogic } from 'scenes/organizationLogic'

import { initKeaTests } from '~/test/init'
import { BillingType } from '~/types'

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

    it('opens the composer with the prefilled message when the support form intent exists at mount', async () => {
        supportLogic.actions.openSupportForm({
            kind: 'bug',
            target_area: 'analytics',
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
                target_area: 'analytics',
                isEmailFormOpen: true,
                target: 'sidePanel',
            })
        }).toFinishAllListeners()

        expect(logic.values.view).toBe('new')
        expect(supportLogic.values.isEmailFormOpen).toBe(false)
    })

    it.each([
        ['analytics', 'list'],
        // Billing problems are answered on every plan
        ['billing', 'new'],
    ])('on a free plan, a %s support CTA lands on the %s view', async (targetArea, expectedView) => {
        logic = sidepanelTicketsLogic.build()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        // After the mount, so the fixture load doesn't put the paid plan back
        setSubscriptionLevel('free')

        await expectLogic(logic, () => {
            supportLogic.actions.openSupportForm({
                kind: 'bug',
                target_area: targetArea as 'analytics' | 'billing',
                isEmailFormOpen: true,
                message: 'It broke',
                target: 'sidePanel',
            })
        }).toFinishAllListeners()

        expect(logic.values.view).toBe(expectedView)
        // Either way the intent is consumed, so supportRouterLogic doesn't keep replaying it
        expect(supportLogic.values.isEmailFormOpen).toBe(false)
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
                target_area: 'billing',
                isEmailFormOpen: true,
                target: 'sidePanel',
            })
        }).toFinishAllListeners()

        // supportLogic has already cleared target_area by now, so an exemption read off it would be gone
        expect(supportLogic.values.targetArea).toBeNull()
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
            target_area: 'analytics',
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

    // The panel already shows free plans the community and upgrade options, and they have no email
    // channel, so warning them the chat failed would offer support they don't actually get.
    it.each([
        ['warns an entitled plan', 'paid', true],
        ['stays quiet on a free plan', 'free', false],
    ])('when the widget never loads, %s', async (_case, subscriptionLevel, expectWarning) => {
        const errorToast = jest.spyOn(lemonToast, 'error').mockReturnValue('' as never)
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
        const unavailable = (posthog.capture as jest.Mock).mock.calls.filter(
            ([event]) => event === 'support widget unavailable'
        )
        expect(unavailable).toHaveLength(1)
        expect(unavailable[0][1]).toMatchObject({ can_create_ticket: expectWarning })
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
            ([event]) => event === 'support ticket send failed'
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
})
