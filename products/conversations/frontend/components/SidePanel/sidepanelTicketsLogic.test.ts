import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { CONVERSATIONS_MESSAGE_MAX_LENGTH, supportLogic } from 'lib/components/Support/supportLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { billingLogic } from 'scenes/billing/billingLogic'

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
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.PRODUCT_SUPPORT_SIDE_PANEL]: true })
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
