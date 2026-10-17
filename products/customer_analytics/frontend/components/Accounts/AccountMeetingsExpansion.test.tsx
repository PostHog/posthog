import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { Provider } from 'kea'
import posthog from 'posthog-js'

import { initKeaTests } from '~/test/init'

import { accountsMeetingsList, accountsRetrieve } from 'products/customer_analytics/frontend/generated/api'
import type { AccountApi, MeetingApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import { AccountMeetingsExpansion } from './AccountMeetingsExpansion'
import { AccountsEvents } from './constants'

jest.mock('products/customer_analytics/frontend/generated/api', () => ({
    ...jest.requireActual('products/customer_analytics/frontend/generated/api'),
    accountsMeetingsList: jest.fn(),
    accountsRetrieve: jest.fn(),
}))

const mockList = accountsMeetingsList as jest.MockedFunction<typeof accountsMeetingsList>
const mockRetrieve = accountsRetrieve as jest.MockedFunction<typeof accountsRetrieve>

class ResizeObserverMock {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

const meeting: MeetingApi = {
    id: 'meeting-1',
    title: 'Quarterly review',
    is_recurring: false,
    gong_url: 'https://app.gong.io/call?id=123',
    start_time: '2026-08-03T15:00:00Z',
    end_time: '2026-08-03T15:30:00Z',
    organizer_email: 'host@example.com',
    status: 'confirmed',
    participants: [],
}

describe('AccountMeetingsExpansion', () => {
    beforeAll(() => {
        ;(global as typeof globalThis & { ResizeObserver: typeof ResizeObserver }).ResizeObserver =
            ResizeObserverMock as unknown as typeof ResizeObserver
    })

    beforeEach(() => {
        initKeaTests()
        jest.resetAllMocks()
        jest.spyOn(posthog, 'capture').mockImplementation(() => undefined)
        mockRetrieve.mockResolvedValue({ id: 'account-1', properties: {} } as AccountApi)
        mockList.mockResolvedValue({ count: 1, next: null, previous: null, results: [meeting] })
    })

    afterEach(() => {
        cleanup()
        jest.useRealTimers()
    })

    test.each([
        { kind: 'future recurring', startTime: '2026-08-04T15:00:00Z', isRecurring: true, badgeCount: 1 },
        { kind: 'past recurring', startTime: '2026-08-02T15:00:00Z', isRecurring: true, badgeCount: 0 },
        { kind: 'future one-off', startTime: '2026-08-04T15:00:00Z', isRecurring: false, badgeCount: 0 },
    ])('renders the recurring badge correctly for a $kind meeting', async ({ startTime, isRecurring, badgeCount }) => {
        jest.useFakeTimers()
        jest.setSystemTime(new Date('2026-08-03T12:00:00Z'))
        mockList.mockResolvedValue({
            count: 1,
            next: null,
            previous: null,
            results: [{ ...meeting, start_time: startTime, is_recurring: isRecurring }],
        })

        render(
            <Provider>
                <AccountMeetingsExpansion accountId="account-1" />
            </Provider>
        )

        expect(await screen.findByText(meeting.title)).toBeInTheDocument()
        expect(screen.queryAllByText('Recurring')).toHaveLength(badgeCount)
    })

    it('opens a matched meeting in Gong', async () => {
        render(
            <Provider>
                <AccountMeetingsExpansion accountId="account-1" />
            </Provider>
        )

        const button = await screen.findByText('Open in Gong')
        expect(button.closest('a')).toHaveAttribute('href', meeting.gong_url)
        expect(button.closest('td')).toHaveTextContent('Quarterly review')
        expect(screen.queryByText('Gong')).not.toBeInTheDocument()

        fireEvent.click(button)
        expect(posthog.capture).toHaveBeenCalledWith(AccountsEvents.GongCallOpened)
    })
})
