import { render } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { DropdownMenu, DropdownMenuContent } from '@posthog/quill'

import { preflightLogic } from 'lib/logic/preflightLogic'

import { SidePanelSupport } from '~/layout/navigation-3000/sidepanel/panels/support/SidePanelSupport'
import { initKeaTests } from '~/test/init'

import {
    liveTicketsLogic,
    sidepanelTicketsLogic,
} from 'products/conversations/frontend/components/SidePanel/sidepanelTicketsLogic'

import { TodayMoreMenuSupportItem } from './TodayMoreMenuSupportItem'
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

    it('shows the open ticket count in the More menu once loaded, without polling', async () => {
        getTickets.mockResolvedValue({
            results: [
                { id: 't1', status: 'open', message_count: 1, created_at: '2026-07-13T00:00:00Z' },
                { id: 't2', status: 'resolved', message_count: 1, created_at: '2026-07-12T00:00:00Z' },
            ],
        })
        const { findByText, queryByText, unmount } = render(
            <DropdownMenu open>
                <DropdownMenuContent>
                    <TodayMoreMenuSupportItem />
                </DropdownMenuContent>
            </DropdownMenu>
        )

        expect(queryByText('No open tickets')).toBeNull()
        expect(await findByText('1 open ticket')).toBeTruthy()
        expect(getTickets).toHaveBeenCalledTimes(1)
        expect(liveTicketsLogic.isMounted()).toBe(false)
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
