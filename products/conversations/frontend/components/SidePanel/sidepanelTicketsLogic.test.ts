import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { supportLogic } from 'lib/components/Support/supportLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import { sidepanelTicketsLogic } from './sidepanelTicketsLogic'

describe('sidepanelTicketsLogic', () => {
    let logic: ReturnType<typeof sidepanelTicketsLogic.build>

    beforeEach(() => {
        initKeaTests()
        ;(posthog as any).conversations = {
            isAvailable: () => true,
            getTickets: jest.fn().mockResolvedValue({ results: [] }),
            getMessages: jest.fn().mockResolvedValue({ messages: [], has_more: false }),
            markAsRead: jest.fn().mockResolvedValue({}),
        }
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.PRODUCT_SUPPORT_SIDE_PANEL]: true })
        supportLogic.mount()
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
                target_area: 'billing',
                isEmailFormOpen: true,
                target: 'sidePanel',
            })
        }).toFinishAllListeners()

        expect(logic.values.view).toBe('new')
        expect(supportLogic.values.isEmailFormOpen).toBe(false)
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
})
