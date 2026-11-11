import { render } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { preflightLogic } from 'lib/logic/preflightLogic'

import { SidePanelSupport } from '~/layout/navigation-3000/sidepanel/panels/support/SidePanelSupport'
import { initKeaTests } from '~/test/init'

import { sidepanelTicketsLogic } from 'products/conversations/frontend/components/SidePanel/sidepanelTicketsLogic'

import { TodaySupportPanel } from './TodaySupportPanel'
import { TodayTopBarPanelTabs } from './TodayTopBarPanelTabs'

describe('support ticket fetching', () => {
    let getTickets: jest.Mock

    beforeEach(() => {
        window.localStorage.clear()
        initKeaTests()
        getTickets = jest.fn().mockResolvedValue({ results: [] })
        ;(posthog as any).conversations = { isAvailable: () => true, getTickets }
        preflightLogic.mount()
        preflightLogic.actions.loadPreflightSuccess({ cloud: true, is_debug: false } as any)
    })

    afterEach(() => {
        delete (posthog as any).conversations
    })

    it('does not fetch from the top bar, which renders on every page', async () => {
        const { getByLabelText, unmount } = render(<TodayTopBarPanelTabs />)
        expect(getByLabelText('Support')).toBeTruthy()

        await expectLogic(sidepanelTicketsLogic).toFinishAllListeners()

        expect(getTickets).not.toHaveBeenCalled()
        unmount()
    })

    it.each([
        ['the Today panel', TodaySupportPanel],
        ['the side panel', SidePanelSupport],
    ])('fetches from %s and keeps existing tickets reachable on a free plan', async (_case, Surface) => {
        getTickets.mockResolvedValue({
            results: [{ id: 't1', status: 'open', message_count: 1, created_at: '2026-07-13T00:00:00Z' }],
        })
        const { findByText, unmount } = render(<Surface />)

        expect(await findByText('Your tickets')).toBeTruthy()
        unmount()
    })
})
